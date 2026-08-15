# coding=utf-8
"""
    @project: MaxKB
    @file： import_service.py
    @date：2026/8/15
    @desc: B4 候选人 CSV 批量导入：逐行校验、疑似重复标注、审计与报告
"""
import csv
import io

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed
from hr.models import Candidate
from hr.serializers.recruitment import RecruitmentService
from hr.services.audit import write_audit_log

IMPORT_HEADERS = [
    "name", "phone", "email", "current_city", "target_city", "highest_degree",
    "years_experience", "skills", "source_type", "source_detail", "collected_at",
    "consent_status", "consent_version", "contact_preference", "source", "note",
]

MAX_IMPORT_ROWS = 200
_SKILL_SEPARATORS = (",", "，", ";", "；")


class ImportService:
    def __init__(self, workspace_id, user_id, hr_role):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.hr_role = hr_role

    def _require_manage(self):
        if self.hr_role != "ADMIN":
            write_audit_log(
                self.workspace_id, self.user_id, "ACCESS_DENIED", "OTHER",
                result="DENIED", detail="Workspace administrator permission is required",
            )
            raise AppUnauthorizedFailed(403, "Workspace administrator permission is required")

    @staticmethod
    def _parse_skills(value):
        if not value:
            return []
        skills = []
        normalized = value.replace("，", ",").replace("、", ",").replace("；", ";").replace(";", ",")
        for part in normalized.split(","):
            skill = part.strip()
            if skill and skill not in skills:
                skills.append(skill)
        return skills

    @staticmethod
    def _normalize_row(row):
        # 过滤 None 值（DictReader 对缺列给 None），让 data.get(field, default) 的默认值生效
        return {
            key.strip(): (value.strip() if isinstance(value, str) else value)
            for key, value in row.items() if value is not None
        }

    def _create_from_row(self, data):
        """校验并创建候选人；返回 (candidate, error)；校验逻辑与 create_candidate 一致。"""
        try:
            years_value = data.get("years_experience")
            if years_value not in (None, ""):
                try:
                    data["years_experience"] = int(str(years_value).strip())
                except (TypeError, ValueError) as exc:
                    raise AppApiException(400, "years_experience is invalid") from exc
            name = RecruitmentService._required_string(data, "name", 128)
            candidate = Candidate.objects.create(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                name=name,
                email=data.get("email") or None,
                phone=RecruitmentService._optional_string(data, "phone", 20),
                current_city=RecruitmentService._optional_string(data, "current_city", 64),
                target_city=RecruitmentService._optional_string(data, "target_city", 64),
                highest_degree=RecruitmentService._optional_string(data, "highest_degree", 32),
                years_experience=RecruitmentService._years_experience(data),
                skills=self._parse_skills(data.get("skills")),
                source=RecruitmentService._optional_string(data, "source", 64),
                source_type=RecruitmentService._source_type(data),
                source_detail=RecruitmentService._optional_string(data, "source_detail", 128),
                collected_at=RecruitmentService._collected_at(data),
                consent_status=RecruitmentService._consent_status(data),
                consent_version=RecruitmentService._optional_string(data, "consent_version", 32),
                contact_preference=RecruitmentService._contact_preference(data),
                note=RecruitmentService._optional_string(data, "note", 4096),
            )
        except AppApiException as exc:
            return None, str(exc)
        return candidate, ""

    @staticmethod
    def _duplicate_hit(candidate, seen_phones, seen_emails):
        """库内或文件内命中即疑似重复（仍创建，仅标注）。"""
        phone = candidate.phone
        email = candidate.email
        if phone and (phone in seen_phones or Candidate.objects.filter(
            workspace_id=candidate.workspace_id, phone=phone
        ).exclude(id=candidate.id).exists()):
            return True
        if email and (email.lower() in seen_emails or Candidate.objects.filter(
            workspace_id=candidate.workspace_id, email__iexact=email
        ).exclude(id=candidate.id).exists()):
            return True
        return False

    def import_candidates_csv(self, content):
        self._require_manage()
        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None:
            raise AppApiException(400, "name is required")
        headers = [header.strip() for header in reader.fieldnames]
        if "name" not in headers:
            raise AppApiException(400, "name is required in csv header")
        rows = list(reader)
        if len(rows) > MAX_IMPORT_ROWS:
            raise AppApiException(400, "at most {} rows per import".format(MAX_IMPORT_ROWS))
        records = []
        seen_phones = set()
        seen_emails = set()
        success = 0
        failed = 0
        duplicates = 0
        for index, row in enumerate(rows):
            row_no = index + 2  # 表头占第 1 行
            data = self._normalize_row(row)
            candidate, error = self._create_from_row(data)
            if candidate is None:
                failed += 1
                records.append({
                    "row_no": row_no, "name": data.get("name", ""), "status": "failed", "reason": error,
                })
                continue
            hit = self._duplicate_hit(candidate, seen_phones, seen_emails)
            if candidate.phone:
                seen_phones.add(candidate.phone)
            if candidate.email:
                seen_emails.add(candidate.email.lower())
            write_audit_log(self.workspace_id, self.user_id, "CREATE", "CANDIDATE", candidate.id)
            if hit:
                duplicates += 1
                records.append({
                    "row_no": row_no, "name": candidate.name, "status": "duplicate",
                    "reason": "疑似与既有候选人重复", "candidate_id": str(candidate.id),
                })
            else:
                success += 1
                records.append({
                    "row_no": row_no, "name": candidate.name, "status": "created",
                    "candidate_id": str(candidate.id),
                })
        write_audit_log(
            self.workspace_id, self.user_id, "IMPORT", "CANDIDATE",
            object_id="", result="SUCCESS",
            detail="total={} success={} failed={} duplicates={}".format(len(rows), success, failed, duplicates),
        )
        return {
            "total": len(rows), "success": success, "failed": failed, "duplicates": duplicates,
            "records": records,
        }

    def import_template(self):
        return IMPORT_HEADERS, {
            "name": "张三", "phone": "13800000000", "email": "zhangsan@example.com",
            "current_city": "上海", "target_city": "北京", "highest_degree": "本科",
            "years_experience": "3", "skills": "Python,Django",
            "source_type": "OTHER", "source_detail": "", "collected_at": "2026-08-15T10:00:00Z",
            "consent_status": "UNKNOWN", "consent_version": "", "contact_preference": "UNSPECIFIED",
            "source": "", "note": "",
        }
