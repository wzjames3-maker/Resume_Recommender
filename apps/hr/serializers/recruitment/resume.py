import hashlib
import logging
import os
import tempfile

import uuid_utils.compat as uuid
from celery_once import AlreadyQueued
from django.db.models import Count, Q

from common.exception.app_exception import AppApiException, NotFound404
from hr.models import (
    ResumeChannel,
    ResumeDatabase,
    ResumeDatabaseMembership,
    ResumeDatabaseStatus,
    ResumeFile,
    ResumeStatus,
)
from hr.services.audit import write_audit_log
from hr.services.flow_log import delete_flow_logs, log_flow
from hr.services.resume_index import delete_resume_index
from hr.services.resume_parser import extract_text_from_docx, extract_text_from_txt
from hr.services.storage import ensure_download_key_scoped, get_storage
from hr.task.resume import parse_resume_task

logger = logging.getLogger("hr")


class ResumeMixin:
    """简历领域：简历库管理、上传/解析、下载/正文/删除/状态批量查询。"""

    def _resume_database(self, database_id, active_only=True):
        try:
            database_uuid = uuid.UUID(str(database_id))
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "resume_database_id is invalid") from exc
        queryset = ResumeDatabase.objects.filter(id=database_uuid, workspace_id=self.workspace_id)
        if active_only:
            queryset = queryset.filter(status=ResumeDatabaseStatus.ACTIVE)
        database = queryset.first()
        if database is None:
            raise NotFound404(404, "Resume database not found")
        return database

    def _default_resume_database(self):
        database = ResumeDatabase.objects.filter(
            workspace_id=self.workspace_id, status=ResumeDatabaseStatus.ACTIVE, is_system=True
        ).first()
        if database is None:
            database = ResumeDatabase.objects.filter(
                workspace_id=self.workspace_id, status=ResumeDatabaseStatus.ACTIVE, is_default=True
            ).first()
        if database is None:
            database = ResumeDatabase.objects.create(
                workspace_id=self.workspace_id, name="总库", is_default=True, is_system=True, user_id=self.user_id
            )
        elif not database.is_system:
            database.is_system = True
            if database.name == "默认简历库":
                database.name = "总库"
            database.save(update_fields=["is_system", "name", "update_time"])
        return database

    def _resume_databases(self, database_ids=None, include_total=True):
        if database_ids is None:
            requested_ids = []
        elif isinstance(database_ids, str):
            requested_ids = [value.strip() for value in database_ids.split(",") if value.strip()]
        elif isinstance(database_ids, (list, tuple, set)):
            requested_ids = [str(value).strip() for value in database_ids if str(value).strip()]
        else:
            raise AppApiException(400, "resume_database_ids must be an array")
        databases = []
        seen = set()
        if include_total:
            total = self._default_resume_database()
            databases.append(total)
            seen.add(str(total.id))
        for database_id in requested_ids:
            database = self._resume_database(database_id)
            if str(database.id) not in seen:
                databases.append(database)
                seen.add(str(database.id))
        if not databases and include_total:
            databases.append(self._default_resume_database())
        return databases

    @staticmethod
    def _attach_resume_databases(resume, databases):
        ResumeDatabaseMembership.objects.bulk_create(
            [ResumeDatabaseMembership(resume_file=resume, resume_database=database) for database in databases],
            ignore_conflicts=True,
        )

    @staticmethod
    def _resume_database_output(database):
        return {
            "id": str(database.id),
            "name": database.name,
            "description": database.description,
            "status": database.status,
            "is_default": database.is_default,
            "is_system": database.is_system,
            "resume_count": getattr(database, "resume_count", database.resume_memberships.count()),
            "candidate_count": getattr(database, "candidate_count", database.resume_memberships.values("resume_file__candidate_id").distinct().count()),
            "pending_count": getattr(database, "pending_count", database.resume_memberships.filter(resume_file__status=ResumeStatus.PENDING).count()),
            "create_time": database.create_time,
            "update_time": database.update_time,
        }

    def list_resume_databases(self):
        self._default_resume_database()
        databases = ResumeDatabase.objects.filter(workspace_id=self.workspace_id).annotate(
            resume_count=Count("resume_memberships__resume_file", distinct=True),
            candidate_count=Count("resume_memberships__resume_file__candidate", distinct=True),
            pending_count=Count("resume_memberships__resume_file", filter=Q(resume_memberships__resume_file__status=ResumeStatus.PENDING), distinct=True),
        ).order_by("-is_system", "-is_default", "create_time")
        return [self._resume_database_output(database) for database in databases]

    def create_resume_database(self, data):
        self._require_manage()
        name = self._required_string(data, "name", 128)
        if ResumeDatabase.objects.filter(workspace_id=self.workspace_id, name=name).exists():
            raise AppApiException(400, "同名简历库已存在")
        description = self._optional_string(data, "description", 512)
        database = ResumeDatabase.objects.create(
            workspace_id=self.workspace_id, name=name, description=description, is_default=False, is_system=False, user_id=self.user_id
        )
        write_audit_log(self.workspace_id, self.user_id, "CREATE", "OTHER", database.id, detail="resume database created")
        return self._resume_database_output(database)

    def archive_resume_database(self, database_id):
        self._require_manage()
        database = self._resume_database(database_id, active_only=False)
        if database.is_system or database.is_default:
            raise AppApiException(400, "总库不能归档")
        if database.status == ResumeDatabaseStatus.ARCHIVED:
            return self._resume_database_output(database)
        database.status = ResumeDatabaseStatus.ARCHIVED
        database.save(update_fields=["status", "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "ARCHIVE", "OTHER", database.id, detail="resume database archived")
        return self._resume_database_output(database)

    @staticmethod
    def _resume_key(workspace_id, sha256, extension):
        return os.path.join("resume", workspace_id, f"{sha256}.{extension}")

    def _resume_output(self, resume):
        memberships = list(
            ResumeDatabaseMembership.objects.filter(resume_file=resume).select_related("resume_database")
        )
        return {
            "id": str(resume.id),
            "file_name": resume.file_name,
            "extension": resume.extension,
            "file_size": resume.file_size,
            "sha256": resume.sha256,
            "source_channel": resume.source_channel,
            "resume_database_id": str(resume.resume_database_id),
            "resume_database_name": resume.resume_database.name if resume.resume_database_id else "",
            "resume_database_ids": [str(item.resume_database_id) for item in memberships],
            "resume_database_names": [item.resume_database.name for item in memberships],
            "status": resume.status,
            # P3 加固：解析失败原因可能含内部异常原文，对 VIEWER 隐藏（OPERATOR/ADMIN 可见）
            "error_message": resume.error_message if self.hr_role != "VIEWER" else "",
            "document_id": str(resume.document_id) if resume.document_id else None,
            "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
            "create_time": resume.create_time,
            "update_time": resume.update_time,
        }

    def upload_resumes(self, files, source_channel, resume_database_ids=None):
        self._require_operator()
        databases = self._resume_databases(resume_database_ids, include_total=True)
        resume_database = databases[0]
        database_ids = [str(database.id) for database in databases]
        database_names = [database.name for database in databases]
        if source_channel not in ResumeChannel.values:
            raise AppApiException(400, "source_channel is invalid")
        records = []
        for file_path, file_name, extension in files:
            extension = extension.lower()
            if extension not in ("docx", "txt"):
                raise AppApiException(400, f"File format {extension} is not supported")
            size = os.path.getsize(file_path)
            if size > 20 * 1024 * 1024:
                raise AppApiException(400, "File exceeds 20 MB limit")
            digest = hashlib.sha256()
            with open(file_path, "rb") as handle:
                digest.update(handle.read())
            sha256 = digest.hexdigest()
            existing = ResumeFile.objects.filter(workspace_id=self.workspace_id, sha256=sha256).first()
            if existing:
                self._attach_resume_databases(existing, databases)
                os.remove(file_path)
                log_flow(self.workspace_id, "UPLOAD", resume_id=existing.id,
                         detail={"file_name": file_name, "file_size": size, "sha256": sha256,
                                  "extension": extension, "duplicate": True})
                records.append({
                    "resume_id": str(existing.id),
                    "file_name": existing.file_name,
                    "status": existing.status,
                    "resume_database_id": str(existing.resume_database_id),
                    "resume_database_name": "、".join(database_names),
                    "resume_database_ids": database_ids,
                    "resume_database_names": database_names,
                    "sha256": existing.sha256,
                    "duplicate": True,
                    "candidate_id": str(existing.candidate_id) if existing.candidate_id else None,
                    "document_id": str(existing.document_id) if existing.document_id else None,
                    "error_message": existing.error_message,
                })
                continue
            stored = get_storage().save(
                self._resume_key(self.workspace_id, sha256, extension), file_path
            )
            os.remove(file_path)
            resume = ResumeFile.objects.create(
                workspace_id=self.workspace_id, file_name=file_name, extension=extension,
                file_path=stored, file_size=size, sha256=sha256,
                source_channel=source_channel, resume_database=resume_database,
                status=ResumeStatus.PENDING, user_id=self.user_id,
            )
            self._attach_resume_databases(resume, databases)
            log_flow(self.workspace_id, "UPLOAD", resume_id=resume.id,
                     detail={"file_name": file_name, "file_size": size, "sha256": sha256,
                             "extension": extension, "duplicate": False})
            try:
                parse_resume_task.delay(str(resume.id))
                status = ResumeStatus.PENDING
                error_message = ""
            except AlreadyQueued as exc:
                raise AppApiException(500, "任务已存在，请稍后查询") from exc
            except Exception as exc:
                # P3 加固：未预期异常原文不直返客户端——服务端记完整日志，响应统一“系统异常”；
                # 原文仅落库 error_message 供 OPERATOR/ADMIN 排查（输出层对 VIEWER 隐藏）。
                logger.exception("简历解析任务投递失败 workspace=%s resume=%s", self.workspace_id, resume.id)
                resume.status = ResumeStatus.FAILED
                resume.error_message = str(exc)
                resume.save(update_fields=["status", "error_message", "update_time"])
                status = ResumeStatus.FAILED
                error_message = "系统异常"
            records.append({
                "resume_id": str(resume.id),
                "file_name": resume.file_name,
                "status": status,
                "resume_database_id": str(resume.resume_database_id),
                "resume_database_name": "、".join(database_names),
                "resume_database_ids": database_ids,
                "resume_database_names": database_names,
                "sha256": resume.sha256,
                "duplicate": False,
                "candidate_id": None,
                "document_id": str(resume.document_id) if resume.document_id else None,
                "error_message": error_message,
            })
        write_audit_log(
            self.workspace_id, self.user_id, "RESUME_UPLOAD", "RESUME",
            object_id=",".join(str(record["resume_id"]) for record in records),
        )
        return records

    def list_candidate_resumes(self, candidate_id):
        candidate = self._candidate(candidate_id)
        resumes = ResumeFile.objects.filter(workspace_id=self.workspace_id, candidate=candidate).order_by("-create_time")
        return [self._resume_output(resume) for resume in resumes]

    def delete_resume(self, resume_id):
        self._require_manage()
        resume = ResumeFile.objects.filter(id=resume_id, workspace_id=self.workspace_id).first()
        if resume is None:
            raise NotFound404(404, "Resource not found")
        # 语义索引联动清理（幂等）+ 流转日志清理（EXTRACT/SANITIZE 含未脱敏全文，删除后不留存）
        delete_resume_index(resume)
        log_flow(self.workspace_id, "LIFECYCLE", resume_id=resume.id,
                 detail={"action": "delete", "document_id": str(resume.document_id) if resume.document_id else None})
        delete_flow_logs(self.workspace_id, resume.id)
        if resume.file_path:
            try:
                get_storage().delete(resume.file_path)
            except OSError:
                pass
        resume.delete()
        write_audit_log(self.workspace_id, self.user_id, "RESUME_DELETE", "RESUME", resume_id)
        return True

    def _resume_file(self, resume_id):
        resume = ResumeFile.objects.filter(id=resume_id, workspace_id=self.workspace_id).first()
        if resume is None:
            raise NotFound404(404, "Resource not found")
        return resume

    def download_resume(self, resume_id):
        self._require_operator()
        resume = self._resume_file(resume_id)
        # P3 加固：下载前断言文件 key 归属当前工作区（workspace 包含性 + 防路径穿越）
        ensure_download_key_scoped(resume.file_path, self.workspace_id)
        if not resume.file_path or not get_storage().exists(resume.file_path):
            raise NotFound404(404, "File not found")
        content_type = {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
        }.get(resume.extension.lower(), "application/octet-stream")
        write_audit_log(self.workspace_id, self.user_id, "RESUME_DOWNLOAD", "RESUME", resume_id)
        return get_storage().open(resume.file_path), resume.file_name, content_type

    def resume_content(self, resume_id):
        self._require_operator()
        resume = self._resume_file(resume_id)
        # P3 加固：读取前断言文件 key 归属当前工作区（workspace 包含性 + 防路径穿越）
        ensure_download_key_scoped(resume.file_path, self.workspace_id)
        if not resume.file_path or not get_storage().exists(resume.file_path):
            raise NotFound404(404, "File not found")
        local_path = get_storage().open(resume.file_path)
        # S3 后端 open 会物化到临时文件，需在使用后清理（P2-26）
        is_temp = local_path.startswith(tempfile.gettempdir()) if local_path else False
        try:
            if resume.extension.lower() == "docx":
                text = extract_text_from_docx(local_path)
            else:
                text = extract_text_from_txt(local_path)
        except Exception as exc:
            raise AppApiException(400, "简历内容提取失败") from exc
        finally:
            if is_temp:
                try:
                    if os.path.exists(local_path):
                        os.remove(local_path)
                except Exception:
                    pass
        return {"content": text}

    def batch_resume_status(self, resume_ids):
        try:
            cleaned_ids = [uuid.UUID(item) for item in resume_ids]
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "ids is invalid") from exc
        resumes = ResumeFile.objects.filter(workspace_id=self.workspace_id, id__in=cleaned_ids)
        return [
            {
                "resume_id": str(resume.id),
                "file_name": resume.file_name,
                "status": resume.status,
                "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
                "document_id": str(resume.document_id) if resume.document_id else None,
                # P3 加固：解析失败原因可能含内部异常原文，对 VIEWER 隐藏（OPERATOR/ADMIN 可见）
                "error_message": resume.error_message if self.hr_role != "VIEWER" else "",
            }
            for resume in resumes
        ]
