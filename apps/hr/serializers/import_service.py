# coding=utf-8
"""
    @project: MaxKB
    @file： import_service.py
    @date：2026/8/15
    @desc: B4 候选人 CSV 批量导入：逐行校验、疑似重复标注、审计与报告（0030 后仅 name/phone/email）
"""
import csv
import io

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed
from hr.models import Candidate
from hr.serializers.recruitment import RecruitmentService
from hr.services.audit import write_audit_log

# 0030 后 Candidate 仅保留 name/phone/email（+ status），其余 13 列已 DROP；模板与导入收敛为三字段
IMPORT_HEADERS = [
    "name", "phone", "email",
]

MAX_IMPORT_ROWS = 200


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
    def _normalize_row(row):
        # 过滤 None 值（DictReader 对缺列给 None），让 data.get(field, default) 的默认值生效
        return {
            key.strip(): (value.strip() if isinstance(value, str) else value)
            for key, value in row.items() if value is not None
        }

    def _create_from_row(self, data):
        """校验并创建候选人；返回 (candidate, error)；仅校验三字段。"""
        try:
            name = RecruitmentService._required_string(data, "name", 128)
            phone = RecruitmentService._optional_string(data, "phone", 20)
            email_raw = data.get("email") or None
            # 邮箱可选，简单规范化（保持与 RecruitmentService 一致的校验在 _optional_string 层已覆盖 phone，email 仅做空值处理）
            email = email_raw.strip() if isinstance(email_raw, str) and email_raw.strip() else None
            # 0030 后不再接收 current_city/target_city/highest_degree/years_experience/skills/source 等 13 列
            # 忽略历史列以保持向后兼容（旧模板仍含这些列时不报错，仅忽略）
            candidate = Candidate.objects.create(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                name=name,
                email=email,
                phone=phone,
            )
        except AppApiException as exc:
            return None, str(exc)
        except Exception as exc:  # 防御：应对旧数据仍传已删字段导致的 TypeError
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
        }
