# coding=utf-8
"""
    @project: MaxKB
    @file： eval_screening.py
    @date：2026/8/17
    @desc: D1 初筛一致性评测（PRD-AGENT-RAG §10）：
           在导入的评测语料（import_resume_dataset）上构造 正/负 人岗匹配对，
           跑真实 Screening Agent（LLM 凭据走 DB，需先注入模型凭据），
           输出一致性报告：总体/正样本/负样本一致率、混淆矩阵、分数带分布、无证据率、平均耗时。
           一致率口径（宽松）：正样本建议非 DECLINE、负样本建议非 ADVANCE。
           门控：RUN_REAL_MODEL=1 才执行（防 CI 误跑）。
           用法：RUN_REAL_MODEL=1 <env> uv run python apps/manage.py eval_screening
                 [--workspace eval-ws] [--limit 200] [--seed 7] [--dry-run]
"""
import json
import os
import random
import time

from django.core.management.base import BaseCommand
from django.db import transaction

from hr.agents.runner import run_screening_agent
from hr.models import Application, Candidate, CandidateSkill, HrAgentRun, HrConfig, Job, JobStage, ResumeFile
from hr.services.application_service import create_default_stages
from hr.services.skill_normalize import normalize_skill
from knowledge.models import Paragraph
from models_provider.models import Model
from models_provider.tools import get_model_instance_by_model_workspace_id


class Command(BaseCommand):
    help = "Screening 初筛一致性评测（真实 LLM，RUN_REAL_MODEL=1 门控）"

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, default="eval-ws", help="评测工作区（含导入语料）")
        parser.add_argument("--limit", type=int, default=200, help="评测对数量（默认 200，控制 LLM 配额）")
        parser.add_argument("--seed", type=int, default=7, help="配对抽样种子（可复现）")
        parser.add_argument("--report", type=str, default=None, help="报告 JSON 路径（默认 logs/screening_eval_{ts}.json）")
        parser.add_argument("--dry-run", action="store_true", help="只打印配对计划不跑模型")

    def _ensure_config(self, workspace_id):
        model = Model.objects.filter(model_name="sensenova-6.8-flash-lite").first()
        if model is None:
            raise RuntimeError("未注册 sensenova-6.8-flash-lite 模型")
        HrConfig.objects.update_or_create(
            workspace_id=workspace_id,
            defaults={"llm_model_id": str(model.id), "agent_enable_screening": True,
                      "agent_max_concurrent_runs": 4, "agent_run_rate_limit": 500},
        )

    def _pair_pool(self, workspace_id):
        return list(
            Candidate.objects.filter(workspace_id=workspace_id).values(
                "id", "name", "skills", "current_city", "years_experience", "highest_degree"
            )
        )

    def _ensure_skills(self, workspace_id, rows, parallel=True):
        """数据集语料技能稀疏（§14#6）：对无技能候选人生成技能（LLM 单次调用，幂等）。
        输入取自其简历语义索引段落文本；失败跳过该候选人不影响评测。"""
        if not parallel:
            return self._backfill_serial(workspace_id, rows)
        from concurrent.futures import ThreadPoolExecutor

        from django.db import close_old_connections

        def worker(row):
            close_old_connections()
            return self._backfill_one(workspace_id, row)

        with ThreadPoolExecutor(max_workers=4) as executor:
            return sum(executor.map(worker, rows))

    def _backfill_serial(self, workspace_id, rows):
        updated = 0
        for row in rows:
            updated += self._backfill_one(workspace_id, row)
        return updated

    def _backfill_one(self, workspace_id, row):
        from hr.services.ai_parser import extract_skills as llm_extract

        if row["skills"]:
            return 0
        config = HrConfig.objects.get(workspace_id=workspace_id)
        try:
            llm = get_model_instance_by_model_workspace_id(config.llm_model_id, workspace_id)
        except Exception:
            return 0
        candidate = Candidate.objects.get(id=row["id"])
        resume = ResumeFile.objects.filter(workspace_id=workspace_id, candidate=candidate).first()
        if resume is None or not resume.document_id:
            return 0
        paragraphs = Paragraph.objects.filter(document_id=resume.document_id).values_list("content", flat=True)
        text = "\n".join(paragraphs)[:1500]
        if len(text) < 20:
            return 0
        try:
            skills = llm_extract(llm, text)
        except Exception:
            return 0
        if not skills:
            return 0
        candidate.skills = skills
        candidate.save(update_fields=["skills", "update_time"])
        CandidateSkill.objects.filter(candidate=candidate).delete()
        seen = set()
        for skill in skills:
            norm = normalize_skill(skill) or skill
            if norm in seen:
                continue
            seen.add(norm)
            CandidateSkill.objects.create(candidate=candidate, skill_norm=norm, skill_raw=skill)
        row["skills"] = skills
        return 1

    def _make_positive(self, candidate):
        """正样本：职位要求取自候选人自身画像（技能/城市），期望不误拒。"""
        skills = (candidate["skills"] or [])[:3]
        return {
            "kind": "positive",
            "candidate": candidate,
            "job": {
                "name": "职位-" + (candidate["name"] or "x"),
                "city": candidate["current_city"] or "",
                "skill_requirements": skills,
                "description": "招聘" + "、".join(skills) + "方向人才，要求具备相关项目经验。",
            },
        }

    def _make_negative(self, candidate, pool):
        """负样本：职位技能取自与候选人不相交的他人画像（结构化硬条件必不满足），期望不误推。"""
        candidate_skills = {s.lower() for s in (candidate["skills"] or [])}
        for other in pool:
            other_skills = {s.lower() for s in (other["skills"] or [])}
            if other["id"] == candidate["id"]:
                continue
            if not (candidate_skills & other_skills) and other_skills:
                skills = sorted(other_skills)[:3]
                return {
                    "kind": "negative",
                    "candidate": candidate,
                    "job": {
                        "name": "职位-" + (other["name"] or "x"),
                        "city": candidate["current_city"] or "未匹配城市",
                        "skill_requirements": skills,
                        "description": "招聘" + "、".join(skills) + "方向人才。",
                    },
                }
        return None

    def _run_case(self, workspace_id, case):
        """建临时 Job/Application → 真实 Screening → 清理；返回建议动作与分数。"""
        job = Job.objects.create(
            workspace_id=workspace_id, name=case["job"]["name"],
            city=case["job"]["city"], skill_requirements=case["job"]["skill_requirements"],
            description=case["job"]["description"],
        )
        create_default_stages(workspace_id, job)
        candidate = Candidate.objects.get(id=case["candidate"]["id"])
        application = Application.objects.create(
            workspace_id=workspace_id, candidate=candidate, job=job,
            relation_type="APPLY", channel="OTHER",
        )
        stage = JobStage.objects.filter(job=job, key="APPLIED").first()
        if stage:
            application.current_stage = stage
            application.save(update_fields=["current_stage", "update_time"])
        try:
            output = run_screening_agent(str(application.id), trigger_type="MANUAL", user_id=None)
            run = HrAgentRun.objects.filter(id=output["run_id"]).first() if output else None
            payload = (run.output_json or {}) if run else {}
            decision = payload.get("decision") or {}
            return {
                "status": output["status"] if output else None,
                "action": output["proposal_action"] if output else None,
                "score": decision.get("score"),
                "evidence_ok": decision.get("evidence_ok"),
                "error": (run.error if run else "")[:200],
            }
        finally:
            with transaction.atomic():
                Application.objects.filter(workspace_id=workspace_id, job=job).delete()
                Job.objects.filter(id=job.id).delete()

    def handle(self, *args, **options):
        if os.environ.get("RUN_REAL_MODEL") != "1":
            self.stdout.write("SKIP: set RUN_REAL_MODEL=1 to run the screening evaluation")
            return
        workspace_id = options["workspace"]
        limit = options["limit"]
        seed = options["seed"]
        report_path = options["report"] or f"logs/screening_eval_{int(time.time())}.json"
        self._ensure_config(workspace_id)

        pool = self._pair_pool(workspace_id)
        if options["dry_run"]:
            pool = [row for row in pool if row["skills"]]
        else:
            filled = self._ensure_skills(workspace_id, pool)
            if filled:
                self.stdout.write(f"技能补抽取 {filled} 人（数据集语料技能稀疏，§14#6）")
            pool = [row for row in pool if row["skills"]]
        if len(pool) < 2:
            self.stderr.write(f"workspace {workspace_id} 可用候选人不足（{len(pool)}），请先 import_resume_dataset")
            return
        rng = random.Random(seed)
        positive_pool = pool[:]
        rng.shuffle(positive_pool)
        cases = []
        for candidate in positive_pool:
            if len(cases) >= limit:
                break
            cases.append(self._make_positive(candidate))
            negative = self._make_negative(candidate, pool)
            if negative:
                cases.append(negative)
            if len(cases) >= limit:
                break
        cases = cases[:limit]
        self.stdout.write(f"配对完成：{len(cases)} 例（正 {sum(1 for c in cases if c['kind'] == 'positive')} / "
                          f"负 {sum(1 for c in cases if c['kind'] == 'negative')}）→ workspace={workspace_id}")
        if options["dry_run"]:
            for case in cases[:5]:
                self.stdout.write(f"  {case['kind']}: {case['candidate']['name']} <- {case['job']['skill_requirements']}")
            return

        records = []
        t0 = time.time()
        from concurrent.futures import ThreadPoolExecutor

        from django.db import close_old_connections

        def eval_one(case):
            close_old_connections()
            result = self._run_case(workspace_id, case)
            action = result["action"]
            if case["kind"] == "positive":
                consistent_loose = action != "DECLINE"
                consistent_strict = action == "ADVANCE"
            else:
                consistent_loose = action != "ADVANCE"
                consistent_strict = action == "DECLINE"
            return {**case, "result": result, "consistent_loose": consistent_loose,
                    "consistent_strict": consistent_strict}

        done = 0
        with ThreadPoolExecutor(max_workers=4) as executor:
            for record in executor.map(eval_one, cases):
                records.append(record)
                done += 1
                if done % 25 == 0:
                    elapsed = time.time() - t0
                    self.stdout.write(f"  ...{done}/{len(cases)}（耗时 {elapsed:.0f}s）")

        # ---------- 报告 ----------
        positive = [r for r in records if r["kind"] == "positive"]
        negative = [r for r in records if r["kind"] == "negative"]
        matrix = {"ADVANCE": 0, "HOLD": 0, "DECLINE": 0}
        for record in records:
            action = record["result"]["action"]
            matrix[action] = matrix.get(action, 0) + 1
        bands = {}
        no_evidence = 0
        for record in records:
            score = record["result"]["score"]
            band = "no-score" if score is None else ("0-59" if score < 60 else ("60-79" if score < 80 else "80-100"))
            bucket = bands.setdefault(band, {"count": 0, "hold": 0})
            bucket["count"] += 1
            if record["result"]["action"] == "HOLD":
                bucket["hold"] += 1
            if record["result"]["evidence_ok"] is False:
                no_evidence += 1

        def rate(items):
            if not items:
                return None
            return round(sum(1 for item in items if item["consistent_loose"]) / len(items), 3)

        report = {
            "workspace": workspace_id, "seed": seed, "total": len(records),
            "positive": len(positive), "negative": len(negative),
            "consistency_loose": rate(records),
            "consistency_loose_positive": rate(positive),
            "consistency_loose_negative": rate(negative),
            "consistency_strict": rate(records),
            "action_matrix": matrix,
            "score_bands": bands,
            "no_evidence_rate": round(no_evidence / len(records), 3) if records else None,
            "avg_duration_s": round((time.time() - t0) / len(records), 2) if records else None,
            "records": records,
        }
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=1, default=str)
        self.stdout.write(self.style.SUCCESS(json.dumps({
            "total": report["total"], "loose_consistency": report["consistency_loose"],
            "positive": report["consistency_loose_positive"], "negative": report["consistency_loose_negative"],
            "strict": report["consistency_strict"], "matrix": report["action_matrix"],
            "bands": report["score_bands"], "no_evidence_rate": report["no_evidence_rate"],
            "avg_duration_s": report["avg_duration_s"],
        }, ensure_ascii=False, indent=1, default=str)))
        self.stdout.write(self.style.SUCCESS(f"report: {report_path}"))
