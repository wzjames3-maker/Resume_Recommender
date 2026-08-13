# coding=utf-8
"""
    @project: MaxKB
    @Author：虎虎
    @file： application.py
    @date：2025/5/26 16:51
    @desc:
"""
from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.views import APIView

from application.api.application_api import ApplicationCreateAPI, ApplicationQueryAPI, \
    ApplicationOperateAPI, ApplicationEditAPI, ApplicationBatchOperateAPI
from application.models import Application
from application.serializers.application import ApplicationSerializer, Query, ApplicationOperateSerializer, \
    ApplicationBatchOperateSerializer
from common import result
from common.auth import TokenAuth
from common.auth.authentication import has_permissions, get_is_permissions, check_batch_permissions
from common.constants.permission_constants import PermissionConstants, RoleConstants, ViewPermission, CompareConstants
from common.log.log import log


def get_application_operation_object(application_id):
    application_model = QuerySet(model=Application).filter(id=application_id).first()
    if application_model is not None:
        return {
            'name': application_model.name
        }
    return {}


def get_application_operation_object_batch(application_id_list):
    application_model_list = QuerySet(model=Application).filter(id__in=application_id_list)
    if application_model_list is not None:
        return {
            "name": f'[{",".join([app.name for app in application_model_list])}]',
            'application_list': [{'name': app.name} for app in application_model_list]
        }
    return {}


class ApplicationAPI(APIView):
    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['POST'],
        description=_('Create an application'),
        summary=_('Create an application'),
        operation_id=_('Create an application'),  # type: ignore
        parameters=ApplicationCreateAPI.get_parameters(),
        request=ApplicationCreateAPI.get_request(),
        responses=ApplicationCreateAPI.get_response(),
        tags=[_('Application')]  # type: ignore
    )
    @has_permissions(PermissionConstants.APPLICATION_CREATE.get_workspace_permission(),
                     RoleConstants.USER.get_workspace_role(),
                     RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
    @log(menu='Application', operate='Create an application',
         get_operation_object=lambda r, k: {'name': r.data.get('name')},
         )
    def post(self, request: Request, workspace_id: str):
        return result.success(
            ApplicationSerializer(data={'workspace_id': workspace_id, 'user_id': request.user.id}).insert(request.data))

    @extend_schema(
        methods=['GET'],
        description=_('Get the application list'),
        summary=_('Get the application list'),
        operation_id=_('Get the application list'),  # type: ignore
        parameters=ApplicationQueryAPI.get_parameters(),
        responses=ApplicationQueryAPI.get_response(),
        tags=[_('Application')]  # type: ignore
    )
    @has_permissions(PermissionConstants.APPLICATION_READ.get_workspace_permission(),
                     RoleConstants.USER.get_workspace_role(),
                     RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
    def get(self, request: Request, workspace_id: str):
        return result.success(
            Query(data={'workspace_id': workspace_id, 'user_id': request.user.id}).list(request.query_params))

    class Page(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['GET'],
            description=_('Get the application list by page'),
            summary=_('Get the application list by page'),
            operation_id=_('Get the application list by page'),  # type: ignore
            parameters=ApplicationQueryAPI.get_parameters(),
            responses=ApplicationQueryAPI.get_page_response(),
            tags=[_('Application')]  # type: ignore
        )
        @has_permissions(PermissionConstants.APPLICATION_READ.get_workspace_permission(),
                         RoleConstants.USER.get_workspace_role(),
                         RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
        def get(self, request: Request, workspace_id: str, current_page: int, page_size: int):
            return result.success(
                Query(data={'workspace_id': workspace_id, 'user_id': request.user.id}).page(current_page, page_size,
                                                                                            request.query_params))

    class Operate(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['DELETE'],
            description=_('Deleting application'),
            summary=_('Deleting application'),
            operation_id=_('Deleting application'),  # type: ignore
            parameters=ApplicationOperateAPI.get_parameters(),
            responses=result.DefaultResultSerializer,
            tags=[_('Application')]  # type: ignore
        )
        @has_permissions(PermissionConstants.APPLICATION_DELETE.get_workspace_application_permission(),
                         PermissionConstants.APPLICATION_DELETE.get_workspace_permission_workspace_manage_role(),
                         ViewPermission([RoleConstants.USER.get_workspace_role()],
                                        [PermissionConstants.APPLICATION.get_workspace_application_permission()],
                                        CompareConstants.AND),
                         RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
        @log(menu='Application', operate='Deleting application',
             get_operation_object=lambda r, k: get_application_operation_object(k.get('application_id')),

             )
        def delete(self, request: Request, workspace_id: str, application_id: str):
            return result.success(ApplicationOperateSerializer(
                data={'application_id': application_id, 'user_id': request.user.id,
                      'workspace_id': workspace_id, }).delete(
                with_valid=True))

        @extend_schema(
            methods=['PUT'],
            description=_('Modify the application'),
            summary=_('Modify the application'),
            operation_id=_('Modify the application'),  # type: ignore
            parameters=ApplicationOperateAPI.get_parameters(),
            request=ApplicationEditAPI.get_request(),
            responses=ApplicationCreateAPI.get_response(),
            tags=[_('Application')]  # type: ignore
        )
        @has_permissions(PermissionConstants.APPLICATION_EDIT.get_workspace_application_permission(),
                         PermissionConstants.APPLICATION_EDIT.get_workspace_permission_workspace_manage_role(),
                         ViewPermission([RoleConstants.USER.get_workspace_role()],
                                        [PermissionConstants.APPLICATION.get_workspace_application_permission()],
                                        CompareConstants.AND),
                         RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
        @log(menu='Application', operate="Modify the application",
             get_operation_object=lambda r, k: get_application_operation_object(k.get('application_id')),
             )
        def put(self, request: Request, workspace_id: str, application_id: str):
            return result.success(
                ApplicationOperateSerializer(
                    data={'application_id': application_id, 'user_id': request.user.id,
                          'workspace_id': workspace_id, }).edit(
                    request.data))

        @extend_schema(
            methods=['GET'],
            description=_('Get application details'),
            summary=_('Get application details'),
            operation_id=_('Get application details'),  # type: ignore
            parameters=ApplicationOperateAPI.get_parameters(),
            request=ApplicationEditAPI.get_request(),
            responses=result.DefaultResultSerializer,
            tags=[_('Application')]  # type: ignore
        )
        @has_permissions(PermissionConstants.APPLICATION_READ.get_workspace_application_permission(),
                         PermissionConstants.APPLICATION_READ.get_workspace_permission_workspace_manage_role(),
                         ViewPermission([RoleConstants.USER.get_workspace_role()],
                                        [PermissionConstants.APPLICATION.get_workspace_application_permission()],
                                        CompareConstants.AND),
                         RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
        def get(self, request: Request, workspace_id: str, application_id: str):
            return result.success(ApplicationOperateSerializer(
                data={'application_id': application_id, 'user_id': request.user.id,
                      'workspace_id': workspace_id, }).one())

    class Move(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['PUT'],
            description=_("Move an application"),
            summary=_("Move an application"),
            operation_id=_("Move an application"),  # type: ignore
            parameters=ApplicationOperateAPI.get_parameters(),
            request=None,
            responses=result.DefaultResultSerializer,
            tags=[_('Application')]  # type: ignore
        )
        @has_permissions(PermissionConstants.APPLICATION_EDIT.get_workspace_application_permission(),
                         PermissionConstants.APPLICATION_EDIT.get_workspace_permission_workspace_manage_role(),
                         ViewPermission([RoleConstants.USER.get_workspace_role()],
                                        [PermissionConstants.APPLICATION.get_workspace_application_permission()],
                                        CompareConstants.AND),
                         RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
        @log(menu='Application', operate='Move an application',
             get_operation_object=lambda r, k: get_application_operation_object(k.get('application_id')))
        def put(self, request: Request, workspace_id: str, application_id: str, folder_id: str):
            return result.success(
                ApplicationOperateSerializer(
                    data={'application_id': application_id, 'user_id': request.user.id,
                          'workspace_id': workspace_id, }).move(folder_id))

    class Publish(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['PUT'],
            description=_("Publishing an application"),
            summary=_("Publishing an application"),
            operation_id=_("Publishing an application"),  # type: ignore
            parameters=ApplicationOperateAPI.get_parameters(),
            request=None,
            responses=result.DefaultResultSerializer,
            tags=[_('Application')]  # type: ignore
        )
        @has_permissions(PermissionConstants.APPLICATION_PUBLISH.get_workspace_application_permission(),
                         PermissionConstants.APPLICATION_PUBLISH.get_workspace_permission_workspace_manage_role(),
                         ViewPermission([RoleConstants.USER.get_workspace_role()],
                                        [PermissionConstants.APPLICATION.get_workspace_application_permission()],
                                        CompareConstants.AND),
                         RoleConstants.WORKSPACE_MANAGE.get_workspace_role())
        @log(menu='Application', operate='Publishing an application',
             get_operation_object=lambda r, k: get_application_operation_object(k.get('application_id')))
        def put(self, request: Request, workspace_id: str, application_id: str):
            return result.success(
                ApplicationOperateSerializer(
                    data={'application_id': application_id, 'user_id': request.user.id,
                          'workspace_id': workspace_id, }).publish(request.data))

    class BatchDelete(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['PUT'],
            description=_("Batch delete applications"),
            summary=_("Batch delete applications"),
            operation_id=_("Batch delete applications"),
            parameters=ApplicationBatchOperateAPI.get_parameters(),
            request=ApplicationBatchOperateAPI.get_request(),
            responses=result.DefaultResultSerializer,
            tags=[_('Application')]
        )
        @has_permissions(PermissionConstants.APPLICATION_BATCH_DELETE.get_workspace_permission(),
                         RoleConstants.USER.get_workspace_role(),
                         RoleConstants.WORKSPACE_MANAGE.get_workspace_role()
                         )
        def put(self, request: Request, workspace_id: str):
            id_list = request.data.get('id_list', [])
            permitted_ids = check_batch_permissions(
                request, id_list, 'application_id',
                (PermissionConstants.APPLICATION_DELETE.get_workspace_application_permission(),
                 PermissionConstants.APPLICATION_DELETE.get_workspace_permission_workspace_manage_role(),
                 ViewPermission([RoleConstants.USER.get_workspace_role()],
                                [PermissionConstants.APPLICATION.get_workspace_application_permission()],
                                CompareConstants.AND),
                 RoleConstants.WORKSPACE_MANAGE.get_workspace_role()), workspace_id=workspace_id
            )
            @log(menu='Application', operate='Batch delete applications',
                 get_operation_object=lambda r, k: get_application_operation_object_batch(permitted_ids))
            def inner(view,r, **kwargs):
                return ApplicationBatchOperateSerializer(
                    data={'workspace_id': workspace_id, 'user_id': request.user.id}
                ).batch_delete({'id_list': permitted_ids})

            return result.success(inner(self,request, workspace_id=workspace_id))

    class BatchMove(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['PUT'],
            description=_("Batch move applications"),
            summary=_("Batch move applications"),
            operation_id=_("Batch move applications"),
            parameters=ApplicationBatchOperateAPI.get_parameters(),
            request=ApplicationBatchOperateAPI.get_move_request(),
            responses=result.DefaultResultSerializer,
            tags=[_('Application')]
        )
        @has_permissions(PermissionConstants.APPLICATION_BATCH_MOVE.get_workspace_permission(),
                         RoleConstants.USER.get_workspace_role(),
                         RoleConstants.WORKSPACE_MANAGE.get_workspace_role()
                         )
        def put(self, request: Request, workspace_id: str):
            id_list = request.data.get('id_list', [])
            permitted_ids = check_batch_permissions(
                request, id_list, 'application_id',
                (PermissionConstants.APPLICATION_EDIT.get_workspace_application_permission(),
                 PermissionConstants.APPLICATION_EDIT.get_workspace_permission_workspace_manage_role(),
                 ViewPermission([RoleConstants.USER.get_workspace_role()],
                                [PermissionConstants.APPLICATION.get_workspace_application_permission()],
                                CompareConstants.AND),
                 RoleConstants.WORKSPACE_MANAGE.get_workspace_role()),
                workspace_id=workspace_id
            )

            @log(menu='Application', operate='Batch move applications',
                 get_operation_object=lambda r, k: get_application_operation_object_batch(permitted_ids))
            def inner(view,r, **kwargs):
                return ApplicationBatchOperateSerializer(
                    data={'workspace_id': workspace_id, 'user_id': request.user.id}
                ).batch_move({'id_list': permitted_ids, 'folder_id': request.data.get('folder_id')})

            return result.success(inner(self,request, workspace_id=workspace_id))

    class BatchCleanTime(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['PUT'],
            description=_("Batch update application chat log clear policy"),
            summary=_("Batch update application chat log clear policy"),
            operation_id=_("Batch update application chat log clear policy"),
            parameters=ApplicationBatchOperateAPI.get_parameters(),
            request=ApplicationBatchOperateAPI.get_clean_time_request(),
            responses=result.DefaultResultSerializer,
            tags=[_('Application')]
        )
        @has_permissions(PermissionConstants.APPLICATION_READ.get_workspace_permission(),
                         RoleConstants.USER.get_workspace_role(),
                         RoleConstants.WORKSPACE_MANAGE.get_workspace_role()
                         )
        def put(self, request: Request, workspace_id: str):
            id_list = request.data.get('id_list', [])
            permitted_ids = check_batch_permissions(
                request, id_list, 'application_id',
                (PermissionConstants.APPLICATION_CHAT_LOG_CLEAR_POLICY.get_workspace_application_permission(),
                 PermissionConstants.APPLICATION_CHAT_LOG_CLEAR_POLICY.get_workspace_permission_workspace_manage_role(),
                 ViewPermission([RoleConstants.USER.get_workspace_role()],
                                [PermissionConstants.APPLICATION.get_workspace_application_permission()],
                                CompareConstants.AND),
                 RoleConstants.WORKSPACE_MANAGE.get_workspace_role()),
                workspace_id=workspace_id
            )

            @log(menu='Application', operate='Batch update application chat log clear policy',
                 get_operation_object=lambda r, k: get_application_operation_object_batch(permitted_ids))
            def inner(view,r, **kwargs):
                return ApplicationBatchOperateSerializer(
                    data={'workspace_id': workspace_id, 'user_id': request.user.id}
                ).batch_clean_time({
                    'id_list': permitted_ids,
                    'clean_time': request.data.get('clean_time'),
                    'file_clean_time': request.data.get('file_clean_time')
                })

            return result.success(inner(self,request, workspace_id=workspace_id))
