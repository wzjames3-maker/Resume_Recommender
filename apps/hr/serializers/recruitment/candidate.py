from functools import reduce
from operator import or_

import uuid_utils.compat as uuid
from django.db import transaction
from django.db.models import Q

from common.exception.app_exception import AppApiException, NotFound404
from hr.models import (
    Application,
    ApplicationStatus,
    Candidate,
    CandidateStatus,
    Offer,
    OnboardingHandoff,
    ResumeFile,
)
from hr.services.audit import write_audit_log
from hr.services.flow_log import delete_flow_logs, log_flow
from hr.services.resume_index import delete_resume_index, set_resume_index_active
from hr.services.storage import get_storage


class CandidateMixin:
    """候选人领域：创建/分页/详情/编辑/归档/恢复/删除/导出/查重/合并。"""

    def _candidate_output(self, candidate):
        masked = self.hr_role == "VIEWER"
        return {
            "id": str(candidate.id),
            "name": candidate.name,
            "email": self._masked_email(candidate.email) if masked else candidate.email,
            "phone": self._masked_phone(candidate.phone) if masked else candidate.phone,
            "status": candidate.status,
            "create_time": candidate.create_time,
            "update_time": candidate.update_time,
        }

    def create_candidate(self, data):
        self._require_operator()
        candidate = Candidate.objects.create(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            name=self._required_string(data, "name", 128),
            email=data.get("email") or None,
            phone=self._optional_string(data, "phone", 20),
        )
        write_audit_log(self.workspace_id, self.user_id, "CREATE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    def _filter_candidates(self, query):
        queryset = Candidate.objects.filter(workspace_id=self.workspace_id)
        name = query.get("name")
        status = query.get("status")
        skills = query.get("skills")
        resume_database_ids = query.getlist("resume_database_ids") if hasattr(query, "getlist") else []
        if not resume_database_ids:
            resume_database_ids = query.get("resume_database_ids") or query.get("resume_database_id")
        if resume_database_ids:
            databases = self._resume_databases(resume_database_ids, include_total=False)
            if not databases:
                queryset = queryset.none()
            else:
                queryset = queryset.filter(
                    resumefile__database_memberships__resume_database_id__in=[database.id for database in databases]
                ).distinct()
        if name:
            queryset = queryset.filter(
                Q(name__icontains=name) | Q(phone__icontains=name) | Q(email__icontains=name)
            )
        if status:
            if status not in CandidateStatus.values:
                raise AppApiException(400, "status is invalid")
            if status == CandidateStatus.DELETED and self.hr_role != "ADMIN":
                queryset = queryset.none()
            else:
                queryset = queryset.filter(status=status)
        else:
            queryset = queryset.exclude(status=CandidateStatus.DELETED)
        if skills:
            # 0030 后 Candidate 仅 name/phone/email：技能搜索改为 纯简历原文/正文 命中（raw_text 优先 + 段落兜底），多词 AND。
            terms = [term.strip() for term in skills.split(",") if term.strip()]
            if terms:
                from knowledge.models import Paragraph
                skills_q = Q()
                resume_doc_ids = list(
                    ResumeFile.objects.filter(workspace_id=self.workspace_id, document_id__isnull=False)
                    .values_list("document_id", flat=True)
                )
                for term in terms:
                    text_doc_ids = list(
                        Paragraph.objects.filter(
                            document_id__in=resume_doc_ids, content__icontains=term, is_active=True
                        ).values_list("document_id", flat=True)
                    )
                    text_candidate_ids = set(
                        ResumeFile.objects.filter(document_id__in=text_doc_ids)
                        .values_list("candidate_id", flat=True)
                    )
                    text_candidate_ids.update(
                        ResumeFile.objects.filter(workspace_id=self.workspace_id, raw_text__icontains=term)
                        .values_list("candidate_id", flat=True)
                    )
                    skills_q &= Q(id__in=text_candidate_ids)
                queryset = queryset.filter(skills_q).distinct()
        owner_id = query.get("owner_id")
        if owner_id:
            owner_id = self._owner_id({"owner_id": owner_id})
            queryset = queryset.filter(
                id__in=Application.objects.filter(
                    workspace_id=self.workspace_id, owner_id=owner_id
                ).values("candidate_id")
            )
        return queryset

    def page_candidates(self, current_page, page_size, query):
        current_page = max(1, int(current_page))  # P3-1: 钳制页码≥1，防 current_page=0 负切片 AssertionError
        queryset = self._filter_candidates(query)
        total = queryset.count()
        start = (current_page - 1) * page_size
        candidates = queryset.order_by("-update_time")[start:start + page_size]
        records = [self._candidate_output(candidate) for candidate in candidates]
        self._attach_duplicate_ids(records, candidates)
        return {"total": total, "records": records}

    def _attach_duplicate_ids(self, records, candidates):
        # 批量预取（P3-2）：phone 精确匹配、email 大小写不敏感各 1 次批量查询，
        # 消除此前 email 逐条 iexact 造成的每行一查 N+1。
        candidates = list(candidates)
        phones = {c.phone for c in candidates if c.phone}
        emails = {c.email for c in candidates if c.email}
        phone_map = {}
        if phones:
            for cand_id, phone in Candidate.objects.filter(workspace_id=self.workspace_id, phone__in=phones).values_list("id", "phone"):
                phone_map.setdefault(phone, set()).add(cand_id)
        email_map = {}
        if emails:
            # 页内全部 email OR 合并为一次 iexact 查询，再按小写 email 分组（与逐条 iexact 同义）
            email_conditions = reduce(or_, (Q(email__iexact=email) for email in emails))
            rows = Candidate.objects.filter(workspace_id=self.workspace_id).filter(email_conditions).values_list("id", "email")
            for cand_id, email in rows:
                email_map.setdefault(email.lower(), set()).add(cand_id)
        for record, candidate in zip(records, candidates):
            dupes = set()
            if candidate.phone and candidate.phone in phone_map:
                dupes.update(phone_map[candidate.phone] - {candidate.id})
            if candidate.email:
                dupes.update(email_map.get(candidate.email.lower(), set()) - {candidate.id})
            record["duplicate_ids"] = [str(item) for item in dupes]

    def get_candidate(self, candidate_id):
        candidate = self._candidate(candidate_id)
        if candidate.status == CandidateStatus.DELETED and self.hr_role != "ADMIN":
            raise NotFound404(404, "Resource not found")
        applications = Application.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
        ).select_related("job", "current_stage").order_by("-update_time")
        result = self._candidate_output(candidate)
        result["applications"] = [
            {
                "id": str(app.id),
                "job_id": str(app.job_id),
                "job_name": app.job.name,
                "status": app.status,
                "current_stage": app.current_stage.key if app.current_stage else "",
                "owner_id": str(app.owner_id) if app.owner_id else None,
            }
            for app in applications
        ]
        write_audit_log(self.workspace_id, self.user_id, "VIEW_DETAIL", "CANDIDATE", candidate.id)
        return result

    def edit_candidate(self, candidate_id, data):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        if candidate.status == CandidateStatus.DELETED:
            raise AppApiException(400, "deleted candidate cannot be edited")
        update_fields = []
        if "name" in data:
            candidate.name = self._required_string(data, "name", 128)
            update_fields.append("name")
        if "phone" in data:
            candidate.phone = self._optional_string(data, "phone", 20)
            update_fields.append("phone")
        if "email" in data:
            email = data.get("email")
            candidate.email = email or None
            if candidate.email and "@" not in candidate.email:
                raise AppApiException(400, "email is invalid")
            update_fields.append("email")
        if not update_fields:
            return self._candidate_output(candidate)
        candidate.save(update_fields=[*update_fields, "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "UPDATE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    def archive_candidate(self, candidate_id):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        if candidate.status == CandidateStatus.DELETED:
            raise AppApiException(400, "deleted candidate cannot be archived")
        if Application.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            status=ApplicationStatus.ACTIVE,
        ).exists():
            raise AppApiException(400, "Candidate has an active assignment")
        candidate.status = CandidateStatus.ARCHIVED
        candidate.save(update_fields=["status", "update_time"])
        for resume in ResumeFile.objects.filter(workspace_id=self.workspace_id, candidate=candidate):
            set_resume_index_active(resume, False)
            log_flow(self.workspace_id, "LIFECYCLE", resume_id=resume.id, document_id=resume.document_id,
                     detail={"action": "archive", "is_active": False})
        write_audit_log(self.workspace_id, self.user_id, "ARCHIVE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    def restore_candidate(self, candidate_id):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        if candidate.status == CandidateStatus.DELETED:
            raise AppApiException(400, "deleted candidate cannot be restored")
        if candidate.status != CandidateStatus.ARCHIVED:
            raise AppApiException(400, "Candidate is not archived")
        candidate.status = CandidateStatus.ACTIVE
        candidate.save(update_fields=["status", "update_time"])
        for resume in ResumeFile.objects.filter(workspace_id=self.workspace_id, candidate=candidate):
            set_resume_index_active(resume, True)
            log_flow(self.workspace_id, "LIFECYCLE", resume_id=resume.id, document_id=resume.document_id,
                     detail={"action": "restore", "is_active": True})
        write_audit_log(self.workspace_id, self.user_id, "RESTORE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    def delete_candidate(self, candidate_id):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        if Application.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            status=ApplicationStatus.ACTIVE,
        ).exists():
            raise AppApiException(400, "Candidate has an active assignment")
        if Application.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            status=ApplicationStatus.HIRED,
        ).exists():
            raise AppApiException(400, "Candidate is hired, cannot delete")
        storage = get_storage()
        for resume in ResumeFile.objects.filter(workspace_id=self.workspace_id, candidate=candidate):
            delete_resume_index(resume)
            log_flow(self.workspace_id, "LIFECYCLE", resume_id=resume.id,
                     detail={"action": "delete", "document_id": str(resume.document_id) if resume.document_id else None})
            delete_flow_logs(self.workspace_id, resume.id)
            file_delete_failed = False
            if resume.file_path and storage.exists(resume.file_path):
                try:
                    storage.delete(resume.file_path)
                except OSError:
                    file_delete_failed = True
            write_audit_log(
                self.workspace_id, resume.user_id or self.user_id, "RESUME_DELETE", "RESUME", resume.id,
                result="FAILED" if file_delete_failed else "SUCCESS",
                detail="resume file removal failed" if file_delete_failed else "",
            )
            resume.delete()
        candidate.name = "已删除候选人"
        candidate.email = None
        candidate.phone = ""
        candidate.status = CandidateStatus.DELETED
        candidate.save(update_fields=["name", "email", "phone", "status", "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "DELETE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    @staticmethod
    def _candidate_export_row(candidate):
        return {
            "name": candidate.name,
            "status": candidate.status,
            "create_time": candidate.create_time.isoformat(),
        }

    def export_candidates(self, filters):
        self._require_manage()
        records = [
            self._candidate_export_row(candidate)
            for candidate in self._filter_candidates(filters)
        ]
        write_audit_log(
            self.workspace_id, self.user_id, "EXPORT", "CANDIDATE",
            detail=f"exported {len(records)} records by user {self.user_id}",
        )
        return records

    def check_duplicate(self, data):
        phone = data.get("phone")
        email = data.get("email")
        exclude_id = data.get("exclude_id")
        if (not isinstance(phone, str) or not phone.strip()) and (not isinstance(email, str) or not email.strip()):
            return {"candidates": []}
        queryset = Candidate.objects.filter(workspace_id=self.workspace_id)
        if exclude_id:
            try:
                uuid.UUID(exclude_id)
            except (ValueError, TypeError) as exc:
                raise AppApiException(400, "exclude_id is invalid") from exc
            queryset = queryset.exclude(id=exclude_id)
        matches = []
        seen = set()
        if isinstance(phone, str) and phone.strip():
            for row in queryset.filter(phone=phone.strip()):
                if row.id not in seen:
                    seen.add(row.id)
                    matches.append(row)
        if isinstance(email, str) and email.strip():
            for row in queryset.filter(email__iexact=email.strip()):
                if row.id not in seen:
                    seen.add(row.id)
                    matches.append(row)
        return {
            "candidates": [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "phone": self._masked_phone(row.phone) if self.hr_role == "VIEWER" else row.phone,
                    "email": self._masked_email(row.email) if self.hr_role == "VIEWER" else row.email,
                }
                for row in matches[:20]
            ]
        }

    def merge_candidates(self, primary_id, data):
        self._require_manage()
        secondary_id = data.get("secondary_id")
        if not isinstance(secondary_id, str) or not secondary_id.strip():
            raise AppApiException(400, "secondary_id is required")
        primary = self._candidate(primary_id)
        secondary = self._candidate(secondary_id)
        if primary.id == secondary.id:
            raise AppApiException(400, "不能与自己合并")
        if primary.status == CandidateStatus.DELETED or secondary.status == CandidateStatus.DELETED:
            raise AppApiException(400, "deleted candidate cannot be merged")
        with transaction.atomic():
            primary = Candidate.objects.select_for_update().get(id=primary.id)
            secondary = Candidate.objects.select_for_update().get(id=secondary.id)
            primary_jobs = set(
                Application.objects.filter(candidate=primary, status=ApplicationStatus.ACTIVE)
                .values_list("job_id", flat=True)
            )
            if Application.objects.filter(
                candidate=secondary, status=ApplicationStatus.ACTIVE, job_id__in=primary_jobs
            ).exists():
                raise AppApiException(400, "存在与主候选人冲突的有效指派，请先调整")
            if not primary.name:
                primary.name = secondary.name
            if not primary.email:
                primary.email = secondary.email
            if not primary.phone:
                primary.phone = secondary.phone
            primary.save(update_fields=["name", "email", "phone", "update_time"])
            ResumeFile.objects.filter(candidate=secondary).update(candidate=primary)
            Application.objects.filter(candidate=secondary).update(candidate=primary)
            # 审查修复 #2：先迁移 Offer/OnboardingHandoff 归属再删 secondary，防止 CASCADE 静默销毁
            Offer.objects.filter(candidate=secondary).update(candidate=primary)
            OnboardingHandoff.objects.filter(candidate=secondary).update(candidate=primary)
            secondary.delete()
        write_audit_log(self.workspace_id, self.user_id, "MERGE", "CANDIDATE", primary.id, detail=str(secondary_id))
        return self.get_candidate(primary_id)
