# coding=utf-8
"""
    @project: MaxKB
    @file： offer.py
    @date：2026/8/15
    @desc: B2 Offer 工件（版本/审批/金额币种/发送/接受/拒绝/撤回/附件）与 B3 入职交接（幂等投递）
"""
import json
import os
import uuid
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    Application,
    ApplicationEventType,
    ApplicationStatus,
    HandoffStatus,
    HandoffTargetType,
    HrConfig,
    Offer,
    OfferApprovalStatus,
    OfferStatus,
    OnboardingHandoff,
)
from hr.services.application_service import write_application_event
from hr.services.audit import write_audit_log
from hr.services.storage import get_storage

_OFFER_TRANSITIONS = {
    OfferStatus.DRAFT: {OfferStatus.SENT},
    OfferStatus.SENT: {OfferStatus.ACCEPTED, OfferStatus.REJECTED, OfferStatus.WITHDRAWN},
}
_ACCEPT_STATUSES = {OfferStatus.ACCEPTED, OfferStatus.REJECTED, OfferStatus.WITHDRAWN}

# P3: Offer 附件类型白名单：扩展名 + 文件头魔数双重校验，拒绝任意类型上传
_OFFER_ATTACHMENT_EXTENSIONS = ("pdf", "doc", "docx", "png", "jpg", "jpeg")
# 扩展名 -> 允许的文件头魔数（内容级 MIME 校验，防止仅改扩展名绕过白名单）
_OFFER_ATTACHMENT_MAGIC = {
    "pdf": (b"%PDF",),
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),  # OLE2
    "docx": (b"PK\x03\x04",),  # OOXML ZIP 容器
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
}


class OfferService:
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

    def _require_operator(self):
        if self.hr_role not in ("OPERATOR", "ADMIN"):
            write_audit_log(
                self.workspace_id, self.user_id, "ACCESS_DENIED", "OTHER",
                result="DENIED", detail="Operator permission is required",
            )
            raise AppUnauthorizedFailed(403, "Operator permission is required")

    def _offer(self, offer_id):
        offer = Offer.objects.filter(id=offer_id, workspace_id=self.workspace_id).first()
        if offer is None:
            raise NotFound404(404, "Resource not found")
        return offer

    @staticmethod
    def _optional_string(data, field, maximum):
        value = data.get(field, "")
        if value is None:
            return ""
        if not isinstance(value, str) or len(value.strip()) > maximum:
            raise AppApiException(400, f"{field} is invalid")
        return value.strip()

    @staticmethod
    def _salary_amount(data):
        value = data.get("salary_amount")
        if value in (None, ""):
            return None
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AppApiException(400, "salary_amount is invalid") from exc
        if amount < 0 or amount > Decimal("999999999999"):
            raise AppApiException(400, "salary_amount is invalid")
        return amount

    @staticmethod
    def _currency(data):
        value = data.get("currency", "CNY")
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 16:
            raise AppApiException(400, "currency is invalid")
        return value.strip()

    @staticmethod
    def _approver_id(data):
        value = data.get("approver_id")
        if value in (None, ""):
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "approver_id is invalid") from exc

    @staticmethod
    def _approval_status(data):
        value = data.get("approval_status")
        if value not in OfferApprovalStatus.values:
            raise AppApiException(400, "approval_status is invalid")
        return value

    @staticmethod
    def _offer_output(offer):
        return {
            "id": str(offer.id),
            "assignment_id": None,
            "application_id": str(offer.application_id) if offer.application_id else None,
            "candidate_id": str(offer.candidate_id),
            "job_id": str(offer.job_id),
            "version": offer.version,
            "status": offer.status,
            "salary_amount": str(offer.salary_amount) if offer.salary_amount is not None else None,
            "currency": offer.currency,
            "approval_status": offer.approval_status,
            "approver_id": str(offer.approver_id) if offer.approver_id else None,
            "approved_at": offer.approved_at,
            "sent_at": offer.sent_at,
            "accepted_at": offer.accepted_at,
            "rejected_at": offer.rejected_at,
            "withdrawn_at": offer.withdrawn_at,
            "note": offer.note,
            "attachment_name": offer.attachment_name,
            "create_time": offer.create_time,
            "update_time": offer.update_time,
        }

    def create_offer_for_application(self, application_id, data):
        """按 Application 创建 Offer：Stage=OFFER、无 DRAFT/SENT 活跃 Offer；版本号唯一约束兜底。"""
        self._require_manage()
        application = Application.objects.filter(id=application_id, workspace_id=self.workspace_id).select_related(
            "candidate", "job", "current_stage"
        ).first()
        if application is None:
            raise NotFound404(404, "Resource not found")
        if application.status != ApplicationStatus.ACTIVE:
            raise AppApiException(400, "Application is not active")
        if application.current_stage is None or application.current_stage.key != "OFFER":
            raise AppApiException(400, "Offer can only be created at OFFER stage")
        if Offer.objects.filter(
            workspace_id=self.workspace_id,
            application=application,
            status__in=[OfferStatus.DRAFT, OfferStatus.SENT],
        ).exists():
            raise AppApiException(400, "An active offer already exists for this application")
        max_version = Offer.objects.filter(
            workspace_id=self.workspace_id, application=application
        ).aggregate(max_version=Max("version"))["max_version"] or 0
        try:
            offer = Offer.objects.create(
                workspace_id=self.workspace_id,
                application=application,
                candidate=application.candidate,
                job=application.job,
                version=max_version + 1,
                salary_amount=self._salary_amount(data),
                currency=self._currency(data),
                note=self._optional_string(data, "note", 4096),
                user_id=self.user_id,
            )
        except IntegrityError as exc:
            raise AppApiException(400, "Offer version conflict, please retry") from exc
        write_audit_log(
            self.workspace_id, self.user_id, "CREATE", "OFFER", offer.id,
            detail=f"application={application.id} v{offer.version}",
        )
        return self._offer_output(offer)

    def list_offers_for_application(self, application_id):
        application = Application.objects.filter(id=application_id, workspace_id=self.workspace_id).first()
        if application is None:
            raise NotFound404(404, "Resource not found")
        offers = Offer.objects.filter(
            workspace_id=self.workspace_id, application=application
        ).order_by("-version")
        return [self._offer_output(offer) for offer in offers]

    def update_offer(self, offer_id, data):
        self._require_manage()
        offer = self._offer(offer_id)
        if offer.status != OfferStatus.DRAFT:
            raise AppApiException(400, "Only draft offer can be edited")
        # 审批后修改需重置审批状态，避免已审批内容被篡改后直接发送（P2-10）
        was_approved = offer.approval_status == OfferApprovalStatus.APPROVED
        changed = False
        if "salary_amount" in data:
            new_val = self._salary_amount(data)
            if new_val != offer.salary_amount:
                changed = True
            offer.salary_amount = new_val
        if "currency" in data:
            new_val = self._currency(data)
            if new_val != offer.currency:
                changed = True
            offer.currency = new_val
        if "note" in data:
            new_val = self._optional_string(data, "note", 4096)
            if new_val != offer.note:
                changed = True
            offer.note = new_val
        if was_approved and changed:
            offer.approval_status = OfferApprovalStatus.PENDING
            offer.approver_id = None
            offer.approved_at = None
        offer.save()
        write_audit_log(self.workspace_id, self.user_id, "UPDATE", "OFFER", offer.id, detail=f"v{offer.version}")
        return self._offer_output(offer)

    def approve_offer(self, offer_id, data):
        self._require_manage()
        offer = self._offer(offer_id)
        if offer.status != OfferStatus.DRAFT:
            raise AppApiException(400, "Only draft offer can be approved")
        offer.approval_status = self._approval_status(data)
        offer.approver_id = self._approver_id(data)
        if offer.approval_status == OfferApprovalStatus.APPROVED:
            offer.approved_at = timezone.now()
        offer.save()
        write_audit_log(
            self.workspace_id, self.user_id, "OFFER_APPROVE", "OFFER", offer.id,
            detail=f"v{offer.version} {offer.approval_status}",
        )
        return self._offer_output(offer)

    def _transition(self, offer, target, timestamp_field, action, detail=""):
        # 原子化：select_for_update + 事务内二次校验，防止并发下旧快照覆写（如 accept 与 withdraw 竞态，P1-13）
        with transaction.atomic():
            locked = Offer.objects.select_for_update().get(id=offer.id, workspace_id=self.workspace_id)
            allowed = _OFFER_TRANSITIONS.get(locked.status)
            if allowed is None or target not in allowed:
                raise AppApiException(
                    400, f"Illegal status transition from {locked.status} to {target}"
                )
            locked.status = target
            setattr(locked, timestamp_field, timezone.now())
            locked.save(update_fields=["status", timestamp_field, "update_time"])
            # 同步回原对象以便调用方继续使用
            offer.status = locked.status
            setattr(offer, timestamp_field, getattr(locked, timestamp_field))
        write_audit_log(
            self.workspace_id, self.user_id, action, "OFFER", offer.id,
            detail=(detail or f"v{offer.version}") + f" {offer.status}",
        )

    def send_offer(self, offer_id):
        self._require_manage()
        offer = self._offer(offer_id)
        if offer.approval_status != OfferApprovalStatus.APPROVED:
            raise AppApiException(400, "Offer must be approved before sending")
        if not offer.application_id:
            raise AppApiException(400, "Offer must be linked to an application")
        # 原子化：锁定同 application 下所有 offer，防止并发双 SENT（P1-13）
        with transaction.atomic():
            # 锁定该 application 的 SENT Offer 行（若存在），否则锁定 application 相关 offer 集合
            Offer.objects.select_for_update().filter(
                workspace_id=self.workspace_id, application_id=offer.application_id, status=OfferStatus.SENT
            ).first()
            sent_query = Q(workspace_id=self.workspace_id, application_id=offer.application_id, status=OfferStatus.SENT)
            if Offer.objects.filter(sent_query).exclude(id=offer.id).exists():
                raise AppApiException(400, "An offer has already been sent")
            # 复用 _transition 的原子逻辑，但已在外层事务中，此处直接调用即可（_transition 内会再次开 savepoint）
            self._transition(offer, OfferStatus.SENT, "sent_at", "OFFER_SEND")
        return self._offer_output(offer)

    def accept_offer(self, offer_id):
        self._require_manage()
        offer = self._offer(offer_id)
        if offer.status != OfferStatus.SENT:
            raise AppApiException(
                400, f"Illegal status transition from {offer.status} to {OfferStatus.ACCEPTED}"
            )
        handoff = None
        with transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer.id)
            self._transition(offer, OfferStatus.ACCEPTED, "accepted_at", "OFFER_ACCEPT")
            if not offer.application_id:
                raise AppApiException(400, "Offer must be linked to an application")
            application = Application.objects.select_for_update().get(id=offer.application_id)
            if application.status != ApplicationStatus.ACTIVE:
                raise AppApiException(400, "Application is not active")
            application.status = ApplicationStatus.HIRED
            application.terminated_at = timezone.now()
            application.save(update_fields=["status", "terminated_at", "update_time"])
            write_application_event(
                self.workspace_id,
                self.user_id,
                application,
                ApplicationEventType.HIRED,
                from_stage=application.current_stage,
                to_stage=application.current_stage,
                from_status=ApplicationStatus.ACTIVE,
                to_status=ApplicationStatus.HIRED,
                reason_code="",
                reason_text=f"offer v{offer.version} accepted",
                idempotency_key=f"offer_accept:{offer.id}",
            )
            write_audit_log(
                self.workspace_id, self.user_id, "ASSIGNMENT_TRANSITION", "APPLICATION",
                application.id, detail="auto to HIRED via offer accept",
            )
            # Handoff 创建与 Offer 接受同事务，幂等 get_or_create，失败随事务回滚（P1-13）
            handoff = OnboardingService(
                self.workspace_id, self.user_id, self.hr_role
            ).create_handoff_for_offer(offer)
        OnboardingService(self.workspace_id, self.user_id, self.hr_role).deliver_handoff(handoff.id)
        return self._offer_output(offer)

    def reject_offer(self, offer_id, data):
        self._require_manage()
        offer = self._offer(offer_id)
        self._transition(offer, OfferStatus.REJECTED, "rejected_at", "OFFER_REJECT")
        if data.get("note"):
            offer.note = self._optional_string(data, "note", 4096)
            offer.save(update_fields=["note", "update_time"])
        return self._offer_output(offer)

    def withdraw_offer(self, offer_id):
        self._require_manage()
        offer = self._offer(offer_id)
        self._transition(offer, OfferStatus.WITHDRAWN, "withdrawn_at", "OFFER_WITHDRAW")
        return self._offer_output(offer)

    def page_offers(self, current_page, page_size, params=None):
        """分页返回当前工作区全部 Offer（供独立 Offer 管理页使用）。"""
        params = params or {}
        queryset = Offer.objects.filter(workspace_id=self.workspace_id).select_related(
            "candidate", "job", "application"
        ).order_by("-update_time")
        status = params.get("status")
        if status:
            queryset = queryset.filter(status=status)
        total = queryset.count()
        start = (current_page - 1) * page_size
        offers = queryset[start:start + page_size]
        records = []
        for offer in offers:
            item = self._offer_output(offer)
            item["candidate_name"] = offer.candidate.name
            item["job_name"] = offer.job.name
            item["assignment_status"] = (
                offer.application.current_stage.key if offer.application and offer.application.current_stage else None
            )
            records.append(item)
        return {"total": total, "records": records}

    def get_offer(self, offer_id):
        return self._offer_output(self._offer(offer_id))

    @staticmethod
    def _attachment_key(workspace_id, offer_id, extension):
        return os.path.join("offer", workspace_id, f"{offer_id}.{extension}")

    @staticmethod
    def _validate_attachment_type(file_path, file_name):
        """附件类型双重校验：扩展名须在白名单内，且文件头魔数须与该类型的 MIME 匹配；任一不通过返回 400。"""
        extension = os.path.splitext(file_name)[1].lstrip(".").lower()
        if extension not in _OFFER_ATTACHMENT_EXTENSIONS:
            raise AppApiException(400, "Attachment type is not allowed (pdf/doc/docx/png/jpg/jpeg only)")
        try:
            with open(file_path, "rb") as handle:
                head = handle.read(8)
        except OSError:
            head = b""
        if not any(head.startswith(magic) for magic in _OFFER_ATTACHMENT_MAGIC[extension]):
            raise AppApiException(400, "Attachment content does not match an allowed file type")

    def upload_offer_attachment(self, offer_id, file_path, file_name):
        self._require_manage()
        offer = self._offer(offer_id)
        if offer.status != OfferStatus.DRAFT:
            raise AppApiException(400, "Only draft offer can change attachment")
        # P3: 先做类型白名单校验（通过后才覆盖旧附件）
        self._validate_attachment_type(file_path, file_name)
        if offer.attachment_path:
            try:
                get_storage().delete(offer.attachment_path)
            except OSError:
                pass
        extension = os.path.splitext(file_name)[1].lstrip(".").lower() or "pdf"
        stored = get_storage().save(
            self._attachment_key(self.workspace_id, offer.id, extension), file_path
        )
        offer.attachment_name = file_name
        offer.attachment_path = stored
        offer.save(update_fields=["attachment_name", "attachment_path", "update_time"])
        write_audit_log(
            self.workspace_id, self.user_id, "UPDATE", "OFFER", offer.id,
            detail=f"v{offer.version} attachment uploaded",
        )
        return self._offer_output(offer)

    def remove_offer_attachment(self, offer_id):
        self._require_manage()
        offer = self._offer(offer_id)
        if offer.status != OfferStatus.DRAFT:
            raise AppApiException(400, "Only draft offer can change attachment")
        if offer.attachment_path:
            try:
                get_storage().delete(offer.attachment_path)
            except OSError:
                pass
        offer.attachment_name = ""
        offer.attachment_path = ""
        offer.save(update_fields=["attachment_name", "attachment_path", "update_time"])
        write_audit_log(
            self.workspace_id, self.user_id, "UPDATE", "OFFER", offer.id,
            detail=f"v{offer.version} attachment removed",
        )
        return self._offer_output(offer)

    def offer_attachment_file(self, offer_id):
        self._require_operator()
        offer = self._offer(offer_id)
        if not offer.attachment_path or not get_storage().exists(offer.attachment_path):
            raise NotFound404(404, "File not found")
        return get_storage().open(offer.attachment_path), offer.attachment_name


class OnboardingService:
    def __init__(self, workspace_id, user_id, hr_role):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.hr_role = hr_role

    @staticmethod
    def _handoff_payload(offer):
        return {
            "candidate_id": str(offer.candidate_id),
            "candidate_name": offer.candidate.name,
            "candidate_phone": offer.candidate.phone or "",
            "candidate_email": offer.candidate.email or "",
            "job_id": str(offer.job_id),
            "job_name": offer.job.name,
            "department": offer.job.department,
            "offer_id": str(offer.id),
            "offer_version": offer.version,
            "salary_amount": str(offer.salary_amount) if offer.salary_amount is not None else None,
            "currency": offer.currency,
            "accepted_at": offer.accepted_at.isoformat() if offer.accepted_at else None,
            "handoff_created_at": timezone.now().isoformat(),
        }

    def create_handoff_for_offer(self, offer):
        """按 Application 唯一（幂等），不重复创建员工记录。"""
        if not offer.application_id:
            raise AppApiException(400, "Offer must be linked to an application")
        handoff, created = OnboardingHandoff.objects.get_or_create(
            workspace_id=self.workspace_id,
            application_id=offer.application_id,
            defaults={
                "application": offer.application,
                "candidate": offer.candidate,
                "job": offer.job,
                "offer": offer,
                "payload": json.dumps(self._handoff_payload(offer), ensure_ascii=False),
                "user_id": self.user_id,
            },
        )
        if not created:
            handoff.payload = json.dumps(self._handoff_payload(offer), ensure_ascii=False)
            handoff.offer = offer
            handoff.application = offer.application
            handoff.save(update_fields=["payload", "offer", "application", "update_time"])
        return handoff

    def _config(self):
        config = HrConfig.objects.filter(workspace_id=self.workspace_id).first()
        target_type = config.handoff_target_type if config else HandoffTargetType.CHECKLIST
        webhook_url = config.handoff_webhook_url if config else ""
        return target_type, webhook_url

    @staticmethod
    def _validate_webhook_url(url: str):
        """Webhook SSRF 防护：仅 https，拒绝 RFC1918 私网/回环/链路本地，长度 ≤512。"""
        from urllib.parse import urlparse
        import ipaddress
        import socket

        if not isinstance(url, str) or not url.strip() or len(url) > 512:
            raise AppApiException(400, "webhook_url is invalid")
        parsed = urlparse(url.strip())
        if parsed.scheme != "https":
            raise AppApiException(400, "webhook_url must be https")
        host = parsed.hostname
        if not host:
            raise AppApiException(400, "webhook_url is invalid")
        lower = host.lower()
        if lower in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            raise AppApiException(400, "webhook_url host is not allowed")

        def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
            # 仅拦截 RFC1918 私网 + 127/8 + ::1 + fe80::/10，避免误拦 198.18/15 等测试保留段
            if ip.is_loopback or ip.is_link_local:
                return True
            # 显式检查 RFC1918
            try:
                if ip.version == 4:
                    return ip in ipaddress.ip_network("10.0.0.0/8") or ip in ipaddress.ip_network("172.16.0.0/12") or ip in ipaddress.ip_network("192.168.0.0/16") or ip in ipaddress.ip_network("127.0.0.0/8")
                else:
                    return ip in ipaddress.ip_network("::1/128") or ip in ipaddress.ip_network("fe80::/10")
            except Exception:
                return ip.is_private

        try:
            ip = ipaddress.ip_address(host)
            if _is_blocked_ip(ip):
                raise AppApiException(400, "webhook_url host is not allowed")
        except ValueError:
            try:
                ip_str = socket.gethostbyname(host)
                ip = ipaddress.ip_address(ip_str)
                if _is_blocked_ip(ip):
                    raise AppApiException(400, "webhook_url host is not allowed")
            except AppApiException:
                raise
            except Exception:
                pass
        return url.strip()

    def _deliver_to_webhook(self, payload):
        target_type, webhook_url = self._config()
        if not webhook_url:
            raise RuntimeError("webhook url is not configured")
        # 校验 URL 合法性（SSRF）
        self._validate_webhook_url(webhook_url)
        # 尝试次数上限（防无限重试）
        # 注意：attempts 在 deliver_handoff 中已 +1，此处校验历史值
        request = Request(
            webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urlopen(request, timeout=10)
            # 检测重定向：urllib 默认跟随，若最终 URL 与原始不同则视为重定向（SSRF 防护）
            try:
                final_url = response.geturl() if hasattr(response, "geturl") else webhook_url
                if final_url != webhook_url:
                    raise RuntimeError("Redirect not allowed")
            except RuntimeError:
                raise
            except Exception:
                pass
            status = getattr(response, "status", 200)
        except HTTPError as exc:
            raise RuntimeError(str(exc)) from exc
        except (URLError, OSError) as exc:
            raise RuntimeError(str(exc)) from exc
        if status < 200 or status >= 300:
            raise RuntimeError(f"webhook returned {status}")

    def deliver_handoff(self, handoff_id):
        """投递交接清单；CHECKLIST 直接产出，WEBHOOK 需 2xx；失败留 FAILED 可重试。"""
        handoff = OnboardingHandoff.objects.filter(id=handoff_id, workspace_id=self.workspace_id).first()
        if handoff is None:
            raise NotFound404(404, "Resource not found")
        # 重试上限：超过 5 次后拒绝，避免无限外发（P2-1）
        if handoff.attempts >= 5:
            raise AppApiException(429, "Too many handoff attempts (max 5)")
        handoff.attempts += 1
        handoff.handoff_time = timezone.now()
        handoff.last_error = ""
        payload = json.loads(handoff.payload)
        target_type, _ = self._config()
        try:
            if target_type == HandoffTargetType.WEBHOOK:
                self._deliver_to_webhook(payload)
            handoff.status = HandoffStatus.SUCCESS
            result = "SUCCESS"
            error = ""
        except (RuntimeError, ValueError, TypeError) as exc:
            handoff.status = HandoffStatus.FAILED
            handoff.last_error = str(exc)[:1024]
            result = "FAILED"
            error = handoff.last_error
        handoff.save(update_fields=["status", "attempts", "handoff_time", "last_error", "update_time"])
        write_audit_log(
            self.workspace_id, self.user_id, "HANDOFF", "ONBOARDING", handoff.id,
            result=result, detail=f"{target_type} attempts={handoff.attempts} {error}".strip(),
        )
        return self._handoff_output(handoff)

    def retry_handoff(self, handoff_id):
        self._require_manage()
        handoff = OnboardingHandoff.objects.filter(id=handoff_id, workspace_id=self.workspace_id).first()
        if handoff is None:
            raise NotFound404(404, "Resource not found")
        if handoff.status != HandoffStatus.FAILED:
            raise AppApiException(400, "Only failed handoff can be retried")
        return self.deliver_handoff(handoff.id)

    def _require_manage(self):
        if self.hr_role != "ADMIN":
            write_audit_log(
                self.workspace_id, self.user_id, "ACCESS_DENIED", "OTHER",
                result="DENIED", detail="Workspace administrator permission is required",
            )
            raise AppUnauthorizedFailed(403, "Workspace administrator permission is required")

    def _require_operator(self):
        if self.hr_role not in ("OPERATOR", "ADMIN"):
            write_audit_log(
                self.workspace_id, self.user_id, "ACCESS_DENIED", "OTHER",
                result="DENIED", detail="Operator permission is required",
            )
            raise AppUnauthorizedFailed(403, "Operator permission is required")

    @staticmethod
    def _masked_phone(phone):
        if not phone or len(phone) <= 7:
            return phone
        return f"{phone[:3]}****{phone[-4:]}"

    @staticmethod
    def _masked_email(email):
        if not email or "@" not in email:
            return email
        local, _, domain = email.partition("@")
        return f"{local[:2]}***@{domain}"

    def _handoff_output(self, handoff):
        payload = {}
        try:
            payload = json.loads(handoff.payload)
        except (ValueError, TypeError):
            pass
        return {
            "id": str(handoff.id),
            "assignment_id": None,
            "application_id": str(handoff.application_id) if handoff.application_id else None,
            "candidate_id": str(handoff.candidate_id),
            "job_id": str(handoff.job_id),
            "offer_id": str(handoff.offer_id),
            "status": handoff.status,
            "attempts": handoff.attempts,
            "last_error": handoff.last_error,
            "handoff_time": handoff.handoff_time,
            "candidate_name": payload.get("candidate_name", ""),
            "job_name": payload.get("job_name", ""),
            "department": payload.get("department", ""),
            "phone": self._masked_phone(payload.get("candidate_phone", "")),
            "email": self._masked_email(payload.get("candidate_email", "")),
            "create_time": handoff.create_time,
            "update_time": handoff.update_time,
        }

    def page_handoffs(self, current_page, page_size):
        self._require_operator()
        queryset = OnboardingHandoff.objects.filter(workspace_id=self.workspace_id)
        total = queryset.count()
        start = (current_page - 1) * page_size
        handoffs = queryset.order_by("-create_time")[start:start + page_size]
        return {"total": total, "records": [self._handoff_output(handoff) for handoff in handoffs]}

    def get_config(self):
        config = HrConfig.objects.filter(workspace_id=self.workspace_id).first()
        return {
            "target_type": config.handoff_target_type if config else HandoffTargetType.CHECKLIST,
            "webhook_url": config.handoff_webhook_url if config else "",
        }

    def put_config(self, data):
        self._require_manage()
        target_type = data.get("target_type")
        if target_type not in HandoffTargetType.values:
            raise AppApiException(400, "target_type is invalid")
        webhook_url = data.get("webhook_url", "")
        if not isinstance(webhook_url, str) or len(webhook_url) > 512:
            raise AppApiException(400, "webhook_url is invalid")
        webhook_url = webhook_url.strip()
        if target_type == HandoffTargetType.WEBHOOK:
            if not webhook_url:
                raise AppApiException(400, "webhook_url is required for WEBHOOK")
            self._validate_webhook_url(webhook_url)
        elif webhook_url:
            # 非 WEBHOOK 模式下若提供 URL 仍需校验合法性
            self._validate_webhook_url(webhook_url)
        config, _ = HrConfig.objects.get_or_create(
            workspace_id=self.workspace_id, defaults={"llm_model_id": ""}
        )
        config.handoff_target_type = target_type
        config.handoff_webhook_url = webhook_url.strip()
        config.save()
        write_audit_log(
            self.workspace_id, self.user_id, "UPDATE", "OTHER", "handoff-config",
            detail=f"{target_type} {webhook_url[:128]}",
        )
        return self.get_config()
