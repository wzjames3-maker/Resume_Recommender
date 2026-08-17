# coding=utf-8
"""
    @project: MaxKB
    @file： hr_offboard_workspace.py
    @date：2026/8/18
    @desc：HR 工作区注销命令（阶段 A）：审计 + 物理清理该工作区 HR 域全部数据（hr_* 全表归零，
          简历语义索引文档/向量 + 简历存储对象一并清空），绝不触碰其它工作区。
          - 默认即 审计+清理；--dry-run 只统计不落库；--export 先输出 JSON 数据返还包再清理；
          - --force 绕过「活跃业务守卫」（有进行中的 Agent 运行 / ACTIVE 流程 / 未关闭职位时拒绝）；
          - 幂等：清理前置入 hr_offboard tombstone（workspace_id 唯一），重复执行报「已注销」不重复删；
          - 留痕：tombstone 记录执行人 / 时间 / 各表计数 / 导出包路径（审计行随 hr_audit_log 一并清空，
            存证以 tombstone 为准）。设计见 specs/2026-08-15-hr-tenant-offboarding-design.md。
          用法：<env> .venv/bin/python apps/manage.py hr_offboard_workspace <workspace_id>
                [--dry-run] [--force] [--export <dir>] [--user-id <uuid>]
"""
import json
import os

import uuid_utils.compat as uuid
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from hr.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    Candidate,
    CandidateSkill,
    HrAccess,
    HrAgentProposal,
    HrAgentRun,
    HrAgentRunStatus,
    HrAuditLog,
    HrConfig,
    HrOffboard,
    Interview,
    Job,
    JobStage,
    JobStatus,
    Offer,
    OnboardingHandoff,
    ResumeFile,
    ResumeFlowLog,
)
from hr.services.audit import write_audit_log
from hr.services.resume_index import delete_resume_knowledge
from hr.services.storage import get_storage
from knowledge.models import Document, Embedding, Knowledge, Paragraph

_RESUME_KNOWLEDGE_NAME = "简历语义索引"


def _masked_phone(phone):
    if not phone or len(phone) <= 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


def _masked_email(email):
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"


class Command(BaseCommand):
    help = "HR 工作区注销：清理该工作区 HR 域全部数据（可 dry-run / export 数据返还包 / force 强制）"

    def add_arguments(self, parser):
        parser.add_argument("workspace_id", help="目标 HR 工作区 ID")
        parser.add_argument("--dry-run", action="store_true", help="只统计不落库（预览将清理的行数/文件数）")
        parser.add_argument("--force", action="store_true", help="绕过活跃业务守卫（有 Agent 在跑/ACTIVE 流程/未关闭职位时需加）")
        parser.add_argument("--export", type=str, default=None, help="数据返还包输出目录（先导出脱敏 JSON 再清理）")
        parser.add_argument("--user-id", type=str, default=None, help="执行人 user id（审计留痕；缺省系统 00000000-0000-0000-0000-000000000000）")

    # ------------------------------------------------------------------ 计数
    @classmethod
    def _storage_keys(cls, workspace_id):
        resume_keys = list(
            ResumeFile.objects.filter(workspace_id=workspace_id)
            .exclude(file_path="").values_list("file_path", flat=True)
        )
        offer_keys = list(
            Offer.objects.filter(workspace_id=workspace_id)
            .exclude(attachment_path="").values_list("attachment_path", flat=True)
        )
        return sorted(set(resume_keys + offer_keys))

    @classmethod
    def _counts(cls, workspace_id):
        resume_kb_ids = list(
            Knowledge.objects.filter(workspace_id=workspace_id, name=_RESUME_KNOWLEDGE_NAME)
            .values_list("id", flat=True)
        )
        document_ids = list(
            Document.objects.filter(knowledge_id__in=resume_kb_ids).values_list("id", flat=True)
        ) if resume_kb_ids else []
        return {
            "applications": Application.objects.filter(workspace_id=workspace_id).count(),
            "application_events": ApplicationEvent.objects.filter(workspace_id=workspace_id).count(),
            "interviews": Interview.objects.filter(workspace_id=workspace_id).count(),
            "offers": Offer.objects.filter(workspace_id=workspace_id).count(),
            "handoffs": OnboardingHandoff.objects.filter(workspace_id=workspace_id).count(),
            "job_stages": JobStage.objects.filter(workspace_id=workspace_id).count(),
            "jobs": Job.objects.filter(workspace_id=workspace_id).count(),
            "candidates": Candidate.objects.filter(workspace_id=workspace_id).count(),
            "candidate_skills": CandidateSkill.objects.filter(candidate__workspace_id=workspace_id).count(),
            "resume_files": ResumeFile.objects.filter(workspace_id=workspace_id).count(),
            "knowledge_documents": len(document_ids),
            "knowledge_paragraphs": (
                Paragraph.objects.filter(knowledge_id__in=resume_kb_ids).count() if resume_kb_ids else 0
            ),
            "knowledge_embeddings": (
                Embedding.objects.filter(document_id__in=document_ids).count() if document_ids else 0
            ),
            "agent_runs": HrAgentRun.objects.filter(workspace_id=workspace_id).count(),
            "agent_proposals": HrAgentProposal.objects.filter(workspace_id=workspace_id).count(),
            "resume_flow_logs": ResumeFlowLog.objects.filter(workspace_id=workspace_id).count(),
            "config": HrConfig.objects.filter(workspace_id=workspace_id).count(),
            "access": HrAccess.objects.filter(workspace_id=workspace_id).count(),
            "audit_logs": HrAuditLog.objects.filter(workspace_id=workspace_id).count(),
            "storage_files": len(cls._storage_keys(workspace_id)),
        }

    # ------------------------------------------------------------------ 守卫
    @classmethod
    def _active_activity(cls, workspace_id):
        """返回活跃业务描述列表（空 = 可无 --force 注销）。"""
        issues = []
        if HrAgentRun.objects.filter(
            workspace_id=workspace_id, status__in=(HrAgentRunStatus.PENDING, HrAgentRunStatus.RUNNING)
        ).exists():
            issues.append("有进行中的 Agent 运行（PENDING/RUNNING）")
        if Application.objects.filter(workspace_id=workspace_id, status=ApplicationStatus.ACTIVE).exists():
            issues.append("有待推进的流程（ACTIVE 申请）")
        if Job.objects.filter(workspace_id=workspace_id).exclude(status=JobStatus.CLOSED).exists():
            issues.append("有未关闭的职位（非 CLOSED）")
        return issues

    # ------------------------------------------------------------------ 导出
    def _export_candidates(self, workspace_id):
        rows = []
        for c in Candidate.objects.filter(workspace_id=workspace_id).order_by("create_time"):
            rows.append({
                "id": str(c.id), "name": c.name,
                "email": _masked_email(c.email), "phone": _masked_phone(c.phone),
                "current_city": c.current_city, "target_city": c.target_city,
                "highest_degree": c.highest_degree, "years_experience": c.years_experience,
                "skills": c.skills, "source": c.source, "source_type": c.source_type,
                "consent_status": c.consent_status, "status": c.status,
                "create_time": c.create_time.isoformat() if c.create_time else None,
                "update_time": c.update_time.isoformat() if c.update_time else None,
            })
        return rows

    def _export_jobs(self, workspace_id):
        rows = []
        for j in Job.objects.filter(workspace_id=workspace_id).order_by("create_time"):
            rows.append({
                "id": str(j.id), "name": j.name, "department": j.department,
                "city": j.city, "level": j.level, "headcount": j.headcount,
                "description": j.description, "skill_requirements": j.skill_requirements,
                "status": j.status, "close_reason": j.close_reason,
                "owner_id": str(j.owner_id) if j.owner_id else None,
                "create_time": j.create_time.isoformat() if j.create_time else None,
            })
        return rows

    def _export_applications(self, workspace_id):
        rows = []
        for app in Application.objects.filter(workspace_id=workspace_id).order_by("create_time"):
            rows.append({
                "id": str(app.id),
                "candidate_id": str(app.candidate_id), "job_id": str(app.job_id),
                "current_stage_id": str(app.current_stage_id) if app.current_stage_id else None,
                "status": app.status, "relation_type": app.relation_type, "channel": app.channel,
                "applied_at": app.applied_at.isoformat() if app.applied_at else None,
                "owner_id": str(app.owner_id) if app.owner_id else None,
                "recruiter_id": str(app.recruiter_id) if app.recruiter_id else None,
                "termination_reason": app.termination_reason,
                "terminated_at": app.terminated_at.isoformat() if app.terminated_at else None,
                "note": app.note,
                "events": [
                    {
                        "event_type": e.event_type,
                        "from_stage": e.from_stage.key if e.from_stage else None,
                        "to_stage": e.to_stage.key if e.to_stage else None,
                        "from_status": e.from_status, "to_status": e.to_status,
                        "reason_code": e.reason_code, "reason_text": e.reason_text,
                        "trace_id": e.trace_id,
                        "create_time": e.create_time.isoformat() if e.create_time else None,
                    }
                    for e in ApplicationEvent.objects.filter(application=app).order_by("create_time")
                ],
            })
        return rows

    def _export_interviews(self, workspace_id):
        rows = []
        for i in Interview.objects.filter(workspace_id=workspace_id).order_by("create_time"):
            rows.append({
                "id": str(i.id), "application_id": str(i.application_id) if i.application_id else None,
                "round_no": i.round_no, "interviewer": i.interviewer, "status": i.status,
                "feedback_deadline": i.feedback_deadline.isoformat() if i.feedback_deadline else None,
                "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
                "create_time": i.create_time.isoformat() if i.create_time else None,
            })
        return rows

    def _export_offers(self, workspace_id):
        rows = []
        for o in Offer.objects.filter(workspace_id=workspace_id).order_by("create_time"):
            rows.append({
                "id": str(o.id), "application_id": str(o.application_id) if o.application_id else None,
                "candidate_id": str(o.candidate_id), "job_id": str(o.job_id),
                "version": o.version, "status": o.status,
                "salary_amount": str(o.salary_amount) if o.salary_amount is not None else None,
                "currency": o.currency, "approval_status": o.approval_status,
                "sent_at": o.sent_at.isoformat() if o.sent_at else None,
                "accepted_at": o.accepted_at.isoformat() if o.accepted_at else None,
                "attachment_name": o.attachment_name,
                "create_time": o.create_time.isoformat() if o.create_time else None,
            })
        return rows

    def _export_handoffs(self, workspace_id):
        rows = []
        for h in OnboardingHandoff.objects.filter(workspace_id=workspace_id).order_by("create_time"):
            rows.append({
                "id": str(h.id), "application_id": str(h.application_id) if h.application_id else None,
                "candidate_id": str(h.candidate_id), "job_id": str(h.job_id),
                "offer_id": str(h.offer_id), "status": h.status,
                "handoff_time": h.handoff_time.isoformat() if h.handoff_time else None,
                "create_time": h.create_time.isoformat() if h.create_time else None,
            })
        return rows

    def _export_audit(self, workspace_id):
        rows = []
        for log in HrAuditLog.objects.filter(workspace_id=workspace_id).order_by("-create_time")[:500]:
            rows.append({
                "action": log.action, "object_type": log.object_type, "object_id": log.object_id,
                "result": log.result,
                "detail": (log.detail[:2000] if log.detail else ""),
                "trace_id": log.trace_id,
                "create_time": log.create_time.isoformat() if log.create_time else None,
            })
        return rows

    def _build_export(self, workspace_id):
        return {
            "workspace_id": workspace_id,
            "exported_at": timezone.now().isoformat(),
            "candidates": self._export_candidates(workspace_id),
            "jobs": self._export_jobs(workspace_id),
            "applications": self._export_applications(workspace_id),
            "interviews": self._export_interviews(workspace_id),
            "offers": self._export_offers(workspace_id),
            "handoffs": self._export_handoffs(workspace_id),
            "audit": self._export_audit(workspace_id),
        }

    def _print_counts(self, workspace_id, counts):
        self.stdout.write(f"workspace {workspace_id} 数据清单（将逐项清理）:")
        for key, value in counts.items():
            self.stdout.write(f"  {key}: {value}")

    # ------------------------------------------------------------------ 主流程
    def handle(self, *args, **options):
        workspace_id = options["workspace_id"]
        force = options["force"]
        dry_run = options["dry_run"]
        export_dir = options.get("export")
        raw_user_id = options.get("user_id")
        try:
            user_id = uuid.UUID(str(raw_user_id)) if raw_user_id else uuid.UUID(int=0)
        except (ValueError, TypeError):
            raise SystemExit("--user-id 不是合法 UUID")

        already = HrOffboard.objects.filter(workspace_id=workspace_id).first()
        if already is not None:
            self.stdout.write(self.style.WARNING(
                f"workspace {workspace_id} 已注销（{already.offboarded_at.isoformat()}，执行人 "
                f"{already.user_id}，计数 {json.dumps(already.counts, ensure_ascii=False)}），无需重复执行"
            ))
            return

        counts = self._counts(workspace_id)
        self._print_counts(workspace_id, counts)

        if dry_run:
            self.stdout.write(self.style.NOTICE("dry-run 完成：以上为将清理的行数/文件数，未做任何删除"))
            return

        if not force:
            issues = self._active_activity(workspace_id)
            if issues:
                self.stdout.write(self.style.ERROR(
                    "工作区存在活跃业务，拒绝注销（确认可清理请加 --force）:\n  - " + "\n  - ".join(issues)
                ))
                return

        # 删除前捕获存储对象 keys（行删除后再查会取不到，须先用）
        storage_keys = self._storage_keys(workspace_id)

        exported_path = ""
        if export_dir:
            payload = self._build_export(workspace_id)
            os.makedirs(export_dir, exist_ok=True)
            file_name = f"hr_offboard_{workspace_id}_{timezone.now().strftime('%Y%m%d%H%M%S')}.json"
            exported_path = os.path.join(export_dir, file_name)
            with open(exported_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
            self.stdout.write(f"exported: {exported_path}")

        with transaction.atomic():
            # 1) 停 Agent 触发（先停再清账本）
            HrConfig.objects.filter(workspace_id=workspace_id).update(agent_enable_screening=False)
            # 2) 简历语义索引（文档/段落/向量 + 知识库本身，幂等，含孤儿文档）
            delete_resume_knowledge(workspace_id)
            # 3) Agent 账本
            HrAgentRun.objects.filter(workspace_id=workspace_id).delete()
            HrAgentProposal.objects.filter(workspace_id=workspace_id).delete()
            # 4) 流程对象（级联 事件/面试/Offer/交接）
            Application.objects.filter(workspace_id=workspace_id).delete()
            # 5) 流程模板 + 职位
            JobStage.objects.filter(workspace_id=workspace_id).delete()
            Job.objects.filter(workspace_id=workspace_id).delete()
            # 6) 候选人（级联技能；简历文件先解绑）
            Candidate.objects.filter(workspace_id=workspace_id).delete()
            ResumeFile.objects.filter(workspace_id=workspace_id).delete()
            # 7) 配置 + 授权（审计行最后清空，留痕以 hr_offboard tombstone 为准）
            if export_dir:
                write_audit_log(workspace_id, user_id, "EXPORT", "OTHER", object_id=workspace_id,
                                detail=f"数据返还导出 candidates={counts['candidates']}, jobs={counts['jobs']}")
            write_audit_log(workspace_id, user_id, "DELETE", "OTHER", object_id=workspace_id,
                            detail=f"workspace offboard 清理 {sum(counts.values())} 行/{counts['storage_files']} 文件")
            HrConfig.objects.filter(workspace_id=workspace_id).delete()
            HrAccess.objects.filter(workspace_id=workspace_id).delete()
            HrAuditLog.objects.filter(workspace_id=workspace_id).delete()
            ResumeFlowLog.objects.filter(workspace_id=workspace_id).delete()
            # 8) 幂等锚点 + 注销留痕
            HrOffboard.objects.create(
                workspace_id=workspace_id, user_id=user_id,
                exported_path=exported_path, counts=counts, force=force,
            )
            # 9) 存储对象（缺失容忍；keys 为删除行前捕获）
            for key in storage_keys:
                try:
                    if get_storage().exists(key):
                        get_storage().delete(key)
                except OSError:
                    pass

        total_rows = sum(counts.values())
        self.stdout.write(self.style.SUCCESS(
            f"workspace {workspace_id} 已注销：清理 {total_rows} 行 / {counts['storage_files']} 存储文件；"
            f"hr_offboard tombstone 已记录"
        ))
