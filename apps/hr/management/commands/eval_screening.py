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
from django.utils import timezone

from hr.agents.runner import run_screening_agent
from hr.models import Application, Candidate, HrAgentRun, HrConfig, Job, JobStage, ResumeFile
from hr.services.application_service import create_default_stages
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
        # 0030 后 Candidate 仅 name/phone/email，历史结构化字段已 DROP；评测基于侯选人姓名构造，技能由 _ensure_skills 按需回填
        return list(
            Candidate.objects.filter(workspace_id=workspace_id).values("id", "name")
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

        if row.get("skills"):
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
        # 0030 后 Candidate 仅 name/phone/email，技能不再落库，评测侧内存回填仅用于构造用例
        row["skills"] = skills
        return 1

    def _candidate_work_profile(self, workspace_id, candidate_id):
        """取候选人简历中工作/项目经历段落，用于渲染完整 JD（报告建议①：消除"泛技能"低估）。"""
        resume = (
            ResumeFile.objects.filter(
                workspace_id=workspace_id, candidate_id=candidate_id, document_id__isnull=False
            ).first()
        )
        if resume is None:
            return None
        paragraphs = Paragraph.objects.filter(document_id=resume.document_id).order_by("position")
        work = [p.content for p in paragraphs if (p.title or "").startswith("工作经历")]
        projects = [p.content for p in paragraphs if (p.title or "").startswith("项目经历")]
        if not work and not projects:
            return None
        return {"work": work, "projects": projects}

    def _role_with_skills(self, profile, skills):
        """选与候选人技能重合最多的单一经历段落（工作经历优先，避免跨职业职责混杂），
        返回 (chunk_text, matched_skills)；无重合返回 (None, [])。"""
        if not profile:
            return None, []
        entries = []
        for chunk in profile["work"] + profile["projects"]:
            lowered = chunk.lower()
            matched = [s for s in skills if s and s.lower() in lowered]
            if matched:
                entries.append((len(matched), chunk, matched))
        if not entries:
            return None, []
        _, chunk, matched = max(entries, key=lambda item: (item[0], len(item[2])))
        return chunk, matched

    def _duties_from_chunk(self, chunk):
        """从单一经历段落提取职责行（工作内容/项目责任），截断复用为 JD 岗位职责。"""
        duties = []
        for line in (chunk or "").splitlines():
            text = line.strip()
            if text.startswith("工作内容：") or text.startswith("项目责任："):
                parts = text.split("：", 1)
                body = (parts[1] if len(parts) > 1 else "").strip()
                if len(body) >= 6:
                    duties.append(body[:180])
                    break
        return duties

    def _make_positive(self, workspace_id, candidate):
        """正样本：职位由候选人单一代表角色渲染的完整 JD（职责 + 技能 + 年限），
        候选人与职位完全匹配，期望不误拒（宽松）甚至 ADVANCE（严格）。"""
        skills = candidate.get("skills") or []
        profile = self._candidate_work_profile(workspace_id, candidate["id"])
        job_skills = skills[:5]
        duties = []
        chunk = None
        if profile:
            chunk, matched = self._role_with_skills(profile, skills)
            if matched:
                job_skills = matched[:5] or job_skills
            elif any(profile["work"]):
                # 无技能重合：回退到首段工作经历职责，且技能只取“该角色片段中出现”的自有技能
                # （避免“首段职责 + 无关全技能”造成职责/技能错配；无命中则 JD 只要求该角色职责）
                chunk = next(c for c in profile["work"] if c)
                in_role = [s for s in skills if s and s.lower() in chunk.lower()]
                job_skills = in_role[:5] or []
            duties = self._duties_from_chunk(chunk)
        if not duties:
            duties_text = "1. 参与核心业务系统/项目的研发与交付；\n2. 与团队协作完成需求分析、方案设计与上线；\n3. 持续优化性能与稳定性。"
        else:
            duties_text = "\n".join(f"{i}. 负责{d}" for i, d in enumerate(duties[:4], 1))
        years = None  # 0030 后 Candidate 无年限字段，已移除
        description = "岗位职责：\n" + duties_text + "\n\n任职要求：\n" + (
            f"- 熟练掌握：{'、'.join(job_skills)}\n" if job_skills else ""
        ) + "- 良好的团队协作与沟通能力"
        return {
            "kind": "positive",
            "candidate": candidate,
            "job": {
                "name": "职位-" + (candidate["name"] or "候选人")[:12],
                "city": "",  # 0030 后无城市字段，已移除
                "skill_requirements": job_skills,
                "description": description,
            },
        }

    def _make_negative(self, candidate, pool):
        """负样本：职位技能取自与候选人不相交的他人画像（结构化硬条件必不满足），期望不误推。"""
        candidate_skills = {s.lower() for s in (candidate.get("skills") or [])}
        for other in pool:
            other_skills = {s.lower() for s in (other.get("skills") or [])}
            if other["id"] == candidate["id"]:
                continue
            if not (candidate_skills & other_skills) and other_skills:
                skills = sorted(other_skills)[:3]
                return {
                    "kind": "negative",
                    "candidate": candidate,
                    "job": {
                        "name": "职位-" + (other["name"] or "x"),
                        "city": "",  # 0030 后无城市字段
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
        # 恢复陈旧 RUNNING/PENDING（如进程被中断遗留），避免并发护栏永久阻塞评测
        HrAgentRun.objects.filter(
            workspace_id=workspace_id,
            status__in=["RUNNING", "PENDING"],
            create_time__lt=timezone.now() - timezone.timedelta(minutes=10),
        ).update(status="FAILED", error="stale run recovered by eval_screening")

        pool = self._pair_pool(workspace_id)
        if options["dry_run"]:
            # 0030 后技能由简历原文按需提取，不再强制要求 Candidate 有技能
            pass
        else:
            filled = self._ensure_skills(workspace_id, pool)
            if filled:
                self.stdout.write(f"技能补抽取 {filled} 人（数据集语料技能稀疏，§14#6）")
            # 0030 后不过滤无技能候选人，RAG 直接基于简历原文
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
            cases.append(self._make_positive(workspace_id, candidate))
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
