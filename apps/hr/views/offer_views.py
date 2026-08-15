# coding=utf-8
"""
    @project: MaxKB
    @file： offer_views.py
    @date：2026/8/15
    @desc: B2 Offer 与 B3 入职交接 API
"""
import os
import tempfile

import uuid_utils.compat as uuid
from django.http import FileResponse
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException
from hr.serializers.offer import OfferService, OnboardingService
from hr.views.permissions import hr_access_required, hr_admin_required


def _offer_service(request, workspace_id):
    return OfferService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        hr_role=getattr(request, "hr_role", None),
    )


def _handoff_service(request, workspace_id):
    return OnboardingService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        hr_role=getattr(request, "hr_role", None),
    )


class OfferListAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, assignment_id):
        return result.success(_offer_service(request, workspace_id).list_offers(assignment_id))

    @hr_admin_required
    def post(self, request, workspace_id, assignment_id):
        return result.success(_offer_service(request, workspace_id).create_offer(assignment_id, request.data))


class OfferDetailAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, offer_id):
        return result.success(_offer_service(request, workspace_id).get_offer(offer_id))

    @hr_admin_required
    def put(self, request, workspace_id, offer_id):
        return result.success(_offer_service(request, workspace_id).update_offer(offer_id, request.data))

    class Approve(APIView):
        authentication_classes = [TokenAuth]

        @hr_admin_required
        def put(self, request, workspace_id, offer_id):
            return result.success(_offer_service(request, workspace_id).approve_offer(offer_id, request.data))

    class Send(APIView):
        authentication_classes = [TokenAuth]

        @hr_admin_required
        def put(self, request, workspace_id, offer_id):
            return result.success(_offer_service(request, workspace_id).send_offer(offer_id))

    class Accept(APIView):
        authentication_classes = [TokenAuth]

        @hr_admin_required
        def put(self, request, workspace_id, offer_id):
            return result.success(_offer_service(request, workspace_id).accept_offer(offer_id))

    class Reject(APIView):
        authentication_classes = [TokenAuth]

        @hr_admin_required
        def put(self, request, workspace_id, offer_id):
            return result.success(_offer_service(request, workspace_id).reject_offer(offer_id, request.data))

    class Withdraw(APIView):
        authentication_classes = [TokenAuth]

        @hr_admin_required
        def put(self, request, workspace_id, offer_id):
            return result.success(_offer_service(request, workspace_id).withdraw_offer(offer_id))

    class Attachment(APIView):
        authentication_classes = [TokenAuth]
        parser_classes = [MultiPartParser]

        @hr_admin_required
        def post(self, request, workspace_id, offer_id):
            upload = request.FILES.get("file")
            if upload is None:
                raise AppApiException(400, "file is required")
            if upload.size > 20 * 1024 * 1024:
                raise AppApiException(400, "File exceeds 20 MB limit")
            temp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid7()}_{upload.name}")
            with open(temp_path, "wb") as handle:
                for chunk in upload.chunks():
                    handle.write(chunk)
            offer = _offer_service(request, workspace_id).upload_offer_attachment(offer_id, temp_path, upload.name)
            os.remove(temp_path)
            return result.success(offer)

        @hr_admin_required
        def delete(self, request, workspace_id, offer_id):
            return result.success(_offer_service(request, workspace_id).remove_offer_attachment(offer_id))

        class Download(APIView):
            authentication_classes = [TokenAuth]

            @hr_access_required
            def get(self, request, workspace_id, offer_id):
                file_path, file_name = _offer_service(request, workspace_id).offer_attachment_file(offer_id)
                try:
                    handle = open(file_path, "rb")
                except OSError as exc:
                    raise AppApiException(500, "文件读取失败") from exc
                return FileResponse(handle, as_attachment=True, filename=file_name)


class HandoffListAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, current_page, page_size):
        return result.success(
            _handoff_service(request, workspace_id).page_handoffs(current_page, page_size)
        )


class HandoffRetryAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def post(self, request, workspace_id, handoff_id):
        return result.success(_handoff_service(request, workspace_id).retry_handoff(handoff_id))


class HandoffConfigAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def get(self, request, workspace_id):
        return result.success(_handoff_service(request, workspace_id).get_config())

    @hr_admin_required
    def put(self, request, workspace_id):
        return result.success(_handoff_service(request, workspace_id).put_config(request.data))
