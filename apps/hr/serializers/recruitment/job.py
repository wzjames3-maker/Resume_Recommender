import uuid_utils.compat as uuid
from django.db.models import Count, Q

from common.exception.app_exception import AppApiException
from hr.models import (
    Application,
    ApplicationStatus,
    Candidate,
    CandidateStatus,
    HrAgentProposal,
    Job,
    JobCloseReason,
    JobStatus,
    ResumeFile,
    TerminationReason,
)
from hr.services.application_service import create_default_stages
from hr.services.audit import write_audit_log


class JobMixin:
    """职位领域：创建/分页/详情/编辑/重开，以及职位-候选人匹配。"""

    @staticmethod
    def _skill_requirements(data):
        value = data.get("skill_requirements", [])
        if not isinstance(value, list) or any(not isinstance(skill, str) or not skill.strip() for skill in value):
            raise AppApiException(400, "skill_requirements must be a list of non-empty strings")
        return [skill.strip() for skill in value]

    @staticmethod
    def _close_reason(data):
        value = data.get("close_reason")
        if not value:
            raise AppApiException(400, "close_reason is required")
        if value not in JobCloseReason.values:
            raise AppApiException(400, "close_reason is invalid")
        return value

    @staticmethod
    def _termination_reason(data):
        value = data.get("termination_reason")
        if not value:
            raise AppApiException(400, "termination_reason is required")
        if value not in TerminationReason.values:
            raise AppApiException(400, "termination_reason is invalid")
        return value

    @staticmethod
    def _job_output(job):
        return {
            "id": str(job.id),
            "name": job.name,
            "department": job.department,
            "city": job.city,
            "level": job.level,
            "headcount": job.headcount,
            "description": job.description,
            "skill_requirements": job.skill_requirements,
            "status": job.status,
            "close_reason": job.close_reason,
            "owner_id": str(job.owner_id) if job.owner_id else None,
            "active_assignment_count": getattr(job, "active_assignment_count", 0),
            "create_time": job.create_time,
            "update_time": job.update_time,
        }

    def create_job(self, data):
        self._require_manage()
        headcount = data.get("headcount", 1)
        if isinstance(headcount, bool) or not isinstance(headcount, int) or not 1 <= headcount <= 999:
            raise AppApiException(400, "headcount must be between 1 and 999")
        job = Job.objects.create(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            owner_id=self._owner_id(data) or self.user_id,
            name=self._required_string(data, "name", 128),
            department=self._optional_string(data, "department", 128),
            city=self._optional_string(data, "city", 64),
            level=self._optional_string(data, "level", 64),
            headcount=headcount,
            description=self._optional_string(data, "description", 4096),
            skill_requirements=self._skill_requirements(data),
        )
        create_default_stages(self.workspace_id, job, self.user_id)
        write_audit_log(self.workspace_id, self.user_id, "CREATE", "JOB", job.id)
        return self._job_output(job)

    def page_jobs(self, current_page, page_size, query):
        current_page = max(1, int(current_page))  # P3-1: 钳制页码≥1，防 current_page=0 负切片 AssertionError
        queryset = Job.objects.filter(workspace_id=self.workspace_id)
        name = query.get("name")
        status = query.get("status")
        owner_id = query.get("owner_id")
        if name:
            queryset = queryset.filter(name__icontains=name)
        if status:
            if status not in JobStatus.values:
                raise AppApiException(400, "status is invalid")
            queryset = queryset.filter(status=status)
        if owner_id:
            queryset = queryset.filter(owner_id=self._owner_id({"owner_id": owner_id}))
        queryset = queryset.annotate(
            active_assignment_count=Count(
                "applications",
                filter=Q(applications__status=ApplicationStatus.ACTIVE),
            )
        )
        total = queryset.count()
        start = (current_page - 1) * page_size
        records = queryset.order_by("-update_time")[start:start + page_size]
        return {"total": total, "records": [self._job_output(job) for job in records]}

    def get_job(self, job_id):
        job = self._job(job_id)
        result = self._job_output(job)
        applications = Application.objects.filter(
            workspace_id=self.workspace_id,
            job=job,
        ).select_related("candidate", "current_stage").order_by("-update_time")
        result["applications"] = [
            {
                "id": str(app.id),
                "candidate_id": str(app.candidate_id),
                "candidate_name": app.candidate.name,
                "status": app.status,
                "current_stage": app.current_stage.key if app.current_stage else "",
                "owner_id": str(app.owner_id) if app.owner_id else None,
            }
            for app in applications
        ]
        applications = Application.objects.filter(
            workspace_id=self.workspace_id,
            job=job,
        ).select_related("candidate", "current_stage").order_by("-update_time")
        result["active_assignment_count"] = applications.filter(status=ApplicationStatus.ACTIVE).count()
        application_records = [
            {
                "application_id": str(application.id),
                "candidate_id": str(application.candidate_id),
                "candidate_name": application.candidate.name,
                "current_stage": {
                    "id": str(application.current_stage.id),
                    "key": application.current_stage.key,
                    "name": application.current_stage.name,
                    "order": application.current_stage.order,
                } if application.current_stage else None,
                "status": application.status,
                "relation_type": application.relation_type,
                "channel": application.channel,
                "owner_id": str(application.owner_id) if application.owner_id else None,
                "reapply_no": application.reapply_no,
                "note": application.note,
                "applied_at": application.applied_at,
                "update_time": application.update_time,
            }
            for application in applications
        ]
        # D1：附带最新 Agent 建议摘要（看板徽标与报告卡入口）
        proposal_by_target = {}
        if application_records:
            proposal_rows = HrAgentProposal.objects.filter(
                workspace_id=self.workspace_id,
                target_type="APPLICATION",
                target_id__in=[record["application_id"] for record in application_records],
            ).order_by("-create_time")
            seen = set()
            for proposal in proposal_rows:
                if proposal.target_id in seen:
                    continue
                seen.add(proposal.target_id)
                proposal_by_target[proposal.target_id] = {
                    "proposal_id": str(proposal.id),
                    "action": proposal.action,
                    "status": proposal.status,
                    "score": (proposal.payload_json or {}).get("decision", {}).get("score"),
                    "create_time": proposal.create_time,
                }
        for record in application_records:
            record["agent"] = proposal_by_target.get(record["application_id"])
        result["applications"] = application_records
        # 前端职位展开行候选人列表读取 assignments（与 candidates 详情保持一致）
        result["assignments"] = application_records
        write_audit_log(self.workspace_id, self.user_id, "VIEW_DETAIL", "JOB", job.id)
        return result

    def edit_job(self, job_id, data):
        self._require_manage()
        job = self._job(job_id)
        fields = {
            "name": (self._required_string, 128),
            "department": (self._optional_string, 128),
            "city": (self._optional_string, 64),
            "level": (self._optional_string, 64),
            "description": (self._optional_string, 4096),
        }
        update_fields = []
        for field, (validator, maximum) in fields.items():
            if field in data:
                setattr(job, field, validator(data, field, maximum))
                update_fields.append(field)
        if "headcount" in data:
            headcount = data["headcount"]
            if isinstance(headcount, bool) or not isinstance(headcount, int) or not 1 <= headcount <= 999:
                raise AppApiException(400, "headcount must be between 1 and 999")
            job.headcount = headcount
            update_fields.append("headcount")
        if "skill_requirements" in data:
            job.skill_requirements = self._skill_requirements(data)
            update_fields.append("skill_requirements")
        if "status" in data:
            if data["status"] not in JobStatus.values:
                raise AppApiException(400, "status is invalid")
            if job.status == JobStatus.CLOSED and data["status"] != JobStatus.CLOSED:
                raise AppApiException(400, "closed job must be reopened via reopen endpoint")
            if data["status"] == JobStatus.CLOSED and job.status != JobStatus.CLOSED:
                raise AppApiException(
                    400, "Use POST /hr/jobs/{id}/close to close a job (requires close_reason and active application handling)"
                )
            if data["status"] == JobStatus.CLOSED:
                job.close_reason = self._close_reason(data)
                update_fields.append("close_reason")
            job.status = data["status"]
            update_fields.append("status")
        if "owner_id" in data:
            job.owner_id = self._owner_id(data)
            update_fields.append("owner_id")
        if "close_reason" in data:
            value = data["close_reason"] or None
            if value is not None and value not in JobCloseReason.values:
                raise AppApiException(400, "close_reason is invalid")
            final_status = data.get("status") or job.status
            if value is not None and final_status != JobStatus.CLOSED:
                raise AppApiException(400, "close_reason only valid for CLOSED status")
            job.close_reason = value
            if "close_reason" not in update_fields:
                update_fields.append("close_reason")
        if update_fields:
            job.save(update_fields=[*update_fields, "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "UPDATE", "JOB", job.id)
        return self._job_output(job)

    def reopen_job(self, job_id):
        self._require_manage()
        job = self._job(job_id)
        if job.status not in (JobStatus.ON_HOLD, JobStatus.CLOSED):
            raise AppApiException(400, "Job is not on hold or closed")
        job.status = JobStatus.OPEN
        job.close_reason = None
        job.save(update_fields=["status", "close_reason", "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "JOB_REOPEN", "JOB", job.id)
        return self._job_output(job)

    def match_job_candidates(self, job_id, current_page, page_size):
        current_page = max(1, int(current_page))  # P3-1: 钳制页码≥1，防 current_page=0 负下标错位
        job = self._job(job_id)
        if job.status != JobStatus.OPEN:
            raise AppApiException(400, "Job is closed")
        requirements = job.skill_requirements
        requirement_lower = [skill.lower() for skill in requirements]
        candidates = Candidate.objects.filter(workspace_id=self.workspace_id, status=CandidateStatus.ACTIVE)
        # 0030 后 Candidate 仅 name/phone/email：匹配仅依赖 简历正文关键词召回（paragraph ILike）与语义补充，不再读 candidate.skills/城市。
        keyword_hit_ids = self._keyword_match_candidate_ids(requirements)
        records = []
        scored_ids = set()
        for candidate in candidates:
            score = 0
            matched = []
            candidate_id_str = str(candidate.id)
            for index, skill in enumerate(requirement_lower):
                if candidate_id_str in keyword_hit_ids.get(skill, ()):
                    score += 2
                    matched.append(requirements[index])
            if score > 0:
                records.append({
                    "candidate_id": str(candidate.id),
                    "name": candidate.name,
                    "match_score": score,
                    "matched_skills": matched,
                    "create_time": candidate.create_time,
                })
                scored_ids.add(str(candidate.id))
        # 语义补充：skills 字段常缺失/为长句，结构化匹配会漏掉简历正文相关的候选人。
        # 用 dense 模式检索简历知识库（显式 dense 跳过结构化技能预筛，避免脏技能表误杀），
        # 命中简历正文的候选人并入匹配结果；知识库/模型缺失时优雅跳过，不影响结构化结果。
        semantic_records = self._semantic_match_candidates(job, requirements, scored_ids)
        # 语义命中补充 create_time（同分时按导入时间排序，近期导入优先展示）
        if semantic_records:
            time_map = dict(
                Candidate.objects.filter(
                    id__in=[record["candidate_id"] for record in semantic_records]
                ).values_list("id", "create_time")
            )
            for record in semantic_records:
                record["create_time"] = time_map.get(uuid.UUID(record["candidate_id"]))
        records.extend(semantic_records)
        from datetime import datetime as _datetime

        records.sort(
            key=lambda item: (item["match_score"], item.get("create_time") or _datetime.min),
            reverse=True,
        )
        total = len(records)
        start = (current_page - 1) * page_size
        return {"total": total, "records": records[start:start + page_size]}

    def _keyword_match_candidate_ids(self, requirements):
        """按需求技能在简历原文（raw_text + paragraph）中做 ILike 关键词召回，返回 {skill_lower: set(candidate_id_str)}。"""
        from knowledge.models import Paragraph

        result = {}
        for skill in requirements:
            term = (skill or "").strip()
            if not term:
                continue
            candidate_ids: set[str] = set()
            # raw_text 优先：覆盖未建 paragraph / document_id 缺口的简历
            raw_ids = ResumeFile.objects.filter(
                workspace_id=self.workspace_id, raw_text__icontains=term
            ).values_list("candidate_id", flat=True)
            for cid in raw_ids:
                if cid:
                    candidate_ids.add(str(cid))
            # paragraph 兜底：覆盖 raw_text 为空的存量简历
            doc_ids = list(
                Paragraph.objects.filter(content__icontains=term).values_list("document_id", flat=True)
            )
            if doc_ids:
                para_ids = ResumeFile.objects.filter(
                    workspace_id=self.workspace_id, document_id__in=doc_ids
                ).values_list("candidate_id", flat=True)
                for cid in para_ids:
                    if cid:
                        candidate_ids.add(str(cid))
            if candidate_ids:
                result[term.lower()] = candidate_ids
        return result

    def _semantic_match_candidates(self, job, requirements, exclude_ids):
        query_parts = [skill for skill in requirements if skill and skill.strip()]
        if job.description:
            query_parts.append(job.description)
        query = " ".join(query_parts).strip()[:200]
        if not query:
            return []
        try:
            from hr.services.resume_search import search_resumes

            result = search_resumes(
                self.workspace_id, query, top_k=20, mode="dense",
                hr_role=self.hr_role, user_id=self.user_id,
            )
        except Exception:
            return []
        items = result.get("items", []) if isinstance(result, dict) else []
        added = []
        seen = set()
        for item in items:
            candidate = item.get("candidate")
            if not isinstance(candidate, dict):
                continue
            cid = str(candidate.get("id") or "")
            if not cid or cid in exclude_ids or cid in seen:
                continue
            seen.add(cid)
            score_map = item.get("score") or {}
            raw = score_map.get("rerank") or score_map.get("dense") or score_map.get("resume") or 0
            # 语义得分映射为与结构化分同量纲的整数（2 分=一项技能精确命中）
            mapped = min(2, max(1, round(float(raw) * 6))) if raw else 1
            added.append({
                "candidate_id": cid,
                "name": candidate.get("name") or "",
                "match_score": mapped,
                "matched_skills": [skill for skill in requirements if skill and skill.strip()],
            })
        return added
