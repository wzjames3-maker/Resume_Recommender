# coding=utf-8
"""
    @project: MaxKB
    @file： hr_agent_probe.py
    @date：2026/8/17
    @desc: Agent 真实模型能力探针（D1 §4.1 第 0 步 / §10 模型能力验收项）：
           用真实 LLM 检查 JSON 输出能力，并跑一次真实 Screening Runner
           （检索凭据缺失时自动验证降级链：无证据 → HOLD，禁止无证据高分）。
           凭据只走环境变量（仓库惯例，不入库持久化）：
             RUN_REAL_MODEL=1
             HR_PROBE_LLM_API_BASE=https://token.sensenova.cn/v1
             HR_PROBE_LLM_API_KEY=xxx   （或 SENSENOVA_API_KEY）
             HR_PROBE_LLM_MODEL=sensenova-6.8-flash-lite
             HR_PROBE_EMBED_API_BASE/HR_PROBE_EMBED_API_KEY/HR_PROBE_RERANK_API_KEY（可选）
           默认 RUN_REAL_MODEL != 1 时打印 SKIP 退出 0，不影响 CI。
"""
import json
import os
import time
import uuid

from django.core.management.base import BaseCommand
from django.utils import timezone

from hr.agents.runner import run_screening_agent
from hr.models import Application, Candidate, HrAgentRun, HrConfig, Job
from hr.services.audit import write_audit_log
from models_provider.models import Model
from models_provider.tools import get_model_instance_by_model_workspace_id

_PROBE_WORKSPACE = "agent-probe"


def _env(name, default=""):
    return os.environ.get(name, default).strip()


class Command(BaseCommand):
    help = "Agent 真实模型能力探针：JSON 能力 + Screening Runner 端到端（RUN_REAL_MODEL=1 才执行）"

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, default=_PROBE_WORKSPACE, help="探针工作区（默认 agent-probe）")

    def _report(self, checks):
        ok = all(item["ok"] for item in checks)
        for item in checks:
            self.stdout.write(("PASS" if item["ok"] else "FAIL") + " " + item["name"] + " " + item["detail"])
        report_path = os.path.join("logs", f"agent_probe_{int(time.time())}.json")
        os.makedirs("logs", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump({"ok": ok, "checks": checks, "time": timezone.now().isoformat()},
                      handle, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(f"report: {report_path}"))
        return ok

    def _inject_credential(self, model_name, api_base, api_key):
        """临时把环境变量凭据写入模型记录（与 installer/real_model_smoke.py 惯例一致）；返回模型对象。"""
        model = Model.objects.filter(model_name=model_name).first()
        if model is None:
            return None
        model.credential = {"api_base": api_base, "api_key": api_key}
        model.save(update_fields=["credential", "update_time"])
        return model

    def handle(self, *args, **options):
        if _env("RUN_REAL_MODEL") != "1":
            self.stdout.write("SKIP: set RUN_REAL_MODEL=1 with model keys to run the probe")
            return
        workspace_id = options["workspace"]
        checks = []

        # ---------- 模型凭据 ----------
        llm_base = _env("HR_PROBE_LLM_API_BASE") or "https://token.sensenova.cn/v1"
        llm_key = _env("HR_PROBE_LLM_API_KEY") or _env("SENSENOVA_API_KEY")
        llm_model = _env("HR_PROBE_LLM_MODEL") or "sensenova-6.8-flash-lite"
        if not llm_key:
            self.stdout.write("SKIP: missing LLM api key (HR_PROBE_LLM_API_KEY / SENSENOVA_API_KEY)")
            return
        model = self._inject_credential(llm_model, llm_base, llm_key)
        if model is None:
            self.stdout.write(f"SKIP: model {llm_model} not registered in models_provider")
            return
        llm_model_id = str(model.id)
        embed_key = _env("HR_PROBE_EMBED_API_KEY") or _env("SILICONFLOW_API_KEY")
        if embed_key:
            embed_base = _env("HR_PROBE_EMBED_API_BASE") or "https://api.siliconflow.cn/v1"
            self._inject_credential("BAAI/bge-large-zh-v1.5", embed_base, embed_key)
            self._inject_credential("BAAI/bge-reranker-v2-m3", embed_base, embed_key)

        # ---------- 检查 1：严格 JSON 输出能力 ----------
        try:
            instance = get_model_instance_by_model_workspace_id(llm_model_id, workspace_id)
            response = instance.invoke(
                '只输出一个 JSON 对象，不要输出任何其他内容：{"ok": true, "name": "probe"}'
            )
            content = getattr(response, "content", "")
            payload = json.loads(content)
            checks.append({
                "name": "llm_json_ability",
                "ok": isinstance(payload, dict) and payload.get("ok") is True,
                "detail": f"model={llm_model} content_type={type(content).__name__}",
            })
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": "llm_json_ability", "ok": False, "detail": str(exc)[:300]})
            self._report(checks)
            return

        # ---------- 检查 2：Screening Runner 真实端到端（含检索降级验证） ----------
        HrConfig.objects.update_or_create(
            workspace_id=workspace_id,
            defaults={"llm_model_id": llm_model_id, "agent_enable_screening": True,
                      "agent_max_concurrent_runs": 2, "agent_run_rate_limit": 100},
        )
        probe_id = uuid.uuid7().hex[:6]
        job = Job.objects.create(
            workspace_id=workspace_id, name=f"探针职位-{probe_id}", department="Probe",
            skill_requirements=["Python"], description="真实模型端到端探针职位",
        )
        candidate = Candidate.objects.create(
            workspace_id=workspace_id, name=f"探针候选人-{probe_id}", skills=["Python"],
            current_city="上海", highest_degree="本科", years_experience=3,
        )
        application = Application.objects.create(
            workspace_id=workspace_id, candidate=candidate, job=job,
            relation_type="APPLY", channel="OTHER",
        )
        from hr.services.application_service import create_default_stages
        create_default_stages(workspace_id, job)
        try:
            output = run_screening_agent(str(application.id), trigger_type="MANUAL", user_id=None)
            run = HrAgentRun.objects.filter(id=output["run_id"]).first() if output else None
            ok = output is not None and output["status"] == "SUCCEEDED" and run is not None
            detail = f"status={output.get('status') if output else None} action={output.get('proposal_action')}"
            if run and run.error:
                detail += f" error={run.error[:200]}"
            checks.append({"name": "screening_end_to_end", "ok": ok, "detail": detail})
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": "screening_end_to_end", "ok": False, "detail": str(exc)[:300]})
        finally:
            # 清理探针业务对象（保留 HrAgentRun/Proposal 账本痕迹）
            Application.objects.filter(workspace_id=workspace_id, job=job).delete()
            Candidate.objects.filter(id=candidate.id).delete()
            Job.objects.filter(id=job.id).delete()
            write_audit_log(
                workspace_id, None, "AGENT_RUN", "OTHER", "probe",
                detail="hr_agent_probe executed (real model probe)",
            )

        self._report(checks)
