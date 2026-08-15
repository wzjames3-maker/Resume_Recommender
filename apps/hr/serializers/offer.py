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

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    AssignmentStatus,
    CandidateAssignment,
    HandoffStatus,
    HandoffTargetType,
    HrConfig,
    Offer,
    OfferApprovalStatus,
    OfferStatus,
    OnboardingHandoff,
)
from hr.services.audit import write_audit_log
from maxkb.const import PROJECT_DIR

_OFFER_TRANSITIONS = {
    OfferStatus.DRAFT: {OfferStatus.SENT},
    OfferStatus.SENT: {OfferStatus.ACCEPTED, OfferStatus.REJECTED, OfferStatus.WITHDRAWN},
}
_ACCEPT_STATUSES = {OfferStatus.ACCEPTED, OfferStatus.REJECTED, OfferStatus.WITHDRAWN}


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
            "assignment_id": str(offer.assignment_id),
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

    def create_offer(self, assignment_id, data):
        self._require_manage()
        assignment = CandidateAssignment.objects.filter(
            id=assignment_id, workspace_id=self.workspace_id
        ).select_related("candidate", "job").first()
        if assignment is None:
            raise NotFound404(404, "Resource not found")
        if assignment.status != AssignmentStatus.OFFER:
            raise AppApiException(400, "Assignment is not in offer status")
        max_version = Offer.objects.filter(
            workspace_id=self.workspace_id, assignment=assignment
        ).aggregate(max_version=Max("version"))["max_version"] or 0
        offer = Offer.objects.create(
            workspace_id=self.workspace_id,
            assignment=assignment,
            candidate=assignment.candidate,
            job=assignment.job,
            version=max_version + 1,
            salary_amount=self._salary_amount(data),
            currency=self._currency(data),
            note=self._optional_string(data, "note", 4096),
            user_id=self.user_id,
        )
        write_audit_log(self.workspace_id, self.user_id, "CREATE", "OFFER", offer.id, detail=f"v{offer.version}")
        return self._offer_output(offer)

    def update_offer(self, offer_id, data):
        self._require_manage()
        offer = self._offer(offer_id)
        if offer.status != OfferStatus.DRAFT:
            raise AppApiException(400, "Only draft offer can be edited")
        if "salary_amount" in data:
            offer.salary_amount = self._salary_amount(data)
        if "currency" in data:
            offer.currency = self._currency(data)
        if "note" in data:
            offer.note = self._optional_string(data, "note", 4096)
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
        allowed = _OFFER_TRANSITIONS.get(offer.status)
        if allowed is None or target not in allowed:
            raise AppApiException(
                400, f"Illegal status transition from {offer.status} to {target}"
            )
        offer.status = target
        setattr(offer, timestamp_field, timezone.now())
        offer.save()
        write_audit_log(
            self.workspace_id, self.user_id, action, "OFFER", offer.id,
            detail=(detail or f"v{offer.version}") + f" {offer.status}",
        )

    def send_offer(self, offer_id):
        self._require_manage()
        offer = self._offer(offer_id)
        self._transition(offer, OfferStatus.SENT, "sent_at", "OFFER_SEND")
        return self._offer_output(offer)

    def accept_offer(self, offer_id):
        self._require_manage()
        offer = self._offer(offer_id)
        if offer.status != OfferStatus.SENT:
            raise AppApiException(
                400, f"Illegal status transition from {offer.status} to {OfferStatus.ACCEPTED}"
            )
        with transaction.atomic():
            offer = Offer.objects.select_for_update().get(id=offer.id)
            self._transition(offer, OfferStatus.ACCEPTED, "accepted_at", "OFFER_ACCEPT")
            assignment = CandidateAssignment.objects.select_for_update().get(id=offer.assignment_id)
            assignment.status = AssignmentStatus.HIRED
            assignment.save(update_fields=["status", "update_time"])
            write_audit_log(
                self.workspace_id, self.user_id, "ASSIGNMENT_TRANSITION", "ASSIGNMENT",
                assignment.id, detail="auto to HIRED via offer accept",
            )
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

    def list_offers(self, assignment_id):
        assignment = CandidateAssignment.objects.filter(
            id=assignment_id, workspace_id=self.workspace_id
        ).first()
        if assignment is None:
            raise NotFound404(404, "Resource not found")
        offers = Offer.objects.filter(
            workspace_id=self.workspace_id, assignment=assignment
        ).order_by("-version")
        return [self._offer_output(offer) for offer in offers]

    def get_offer(self, offer_id):
        return self._offer_output(self._offer(offer_id))

    def _attachment_dir(self):
        directory = os.path.join(PROJECT_DIR, "data", "offer", self.workspace_id)
        os.makedirs(directory, exist_ok=True)
        return directory

    def upload_offer_attachment(self, offer_id, file_path, file_name):
        self._require_manage()
        offer = self._offer(offer_id)
        if offer.attachment_path and os.path.exists(offer.attachment_path):
            try:
                os.remove(offer.attachment_path)
            except OSError:
                pass
        extension = os.path.splitext(file_name)[1].lstrip(".").lower() or "pdf"
        stored = os.path.join(self._attachment_dir(), f"{offer.id}.{extension}")
        with open(file_path, "rb") as source, open(stored, "wb") as target:
            target.write(source.read())
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
        if offer.attachment_path and os.path.exists(offer.attachment_path):
            try:
                os.remove(offer.attachment_path)
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
        if not offer.attachment_path or not os.path.exists(offer.attachment_path):
            raise NotFound404(404, "File not found")
        return offer.attachment_path, offer.attachment_name


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
        """按指派唯一（幂等），不重复创建员工记录。"""
        handoff, created = OnboardingHandoff.objects.get_or_create(
            workspace_id=self.workspace_id,
            assignment_id=offer.assignment_id,
            defaults={
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
            handoff.save(update_fields=["payload", "offer", "update_time"])
        return handoff

    def _config(self):
        config = HrConfig.objects.filter(workspace_id=self.workspace_id).first()
        target_type = config.handoff_target_type if config else HandoffTargetType.CHECKLIST
        webhook_url = config.handoff_webhook_url if config else ""
        return target_type, webhook_url

    def _deliver_to_webhook(self, payload):
        target_type, webhook_url = self._config()
        if not webhook_url:
            raise RuntimeError("webhook url is not configured")
        request = Request(
            webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urlopen(request, timeout=10)
            status = getattr(response, "status", 200)
        except (HTTPError, URLError, OSError) as exc:
            raise RuntimeError(str(exc)) from exc
        if status < 200 or status >= 300:
            raise RuntimeError(f"webhook returned {status}")

    def deliver_handoff(self, handoff_id):
        """投递交接清单；CHECKLIST 直接产出，WEBHOOK 需 2xx；失败留 FAILED 可重试。"""
        handoff = OnboardingHandoff.objects.filter(id=handoff_id, workspace_id=self.workspace_id).first()
        if handoff is None:
            raise NotFound404(404, "Resource not found")
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
            "assignment_id": str(handoff.assignment_id),
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
