"""
    @project: MaxKB-xpack-ee
    @Author: niu
    @file: shared_resource_auth.py
    @date: 2026/3/11 11:22
    @desc:
"""
from typing import List

from django.db.models import QuerySet

from common.database_model_manage.database_model_manage import DatabaseModelManage
from knowledge.models import Knowledge


def get_runtime_user_id(user_id=None, chat_user_id=None, chat_user_type=None):
    if user_id:
        return str(user_id)
    return None


def filter_authorized_ids(resource_type: str, ids: List[str], workspace_id: str, user_id=None) -> List[str]:
    """
    通用授权过滤函数

    @param resource_type: 资源类型 ('model', 'knowledge')
    @param ids: 待过滤的ID列表
    @param workspace_id: 工作空间ID
    @return: 授权通过的ID列表
    """

    if not ids:
        return []

    model_class = {'knowledge': Knowledge}.get(resource_type)
    if model_class is None:
        return ids

    auth_func = DatabaseModelManage.get_model(f"get_authorized_{resource_type}")

    same_workspace_ids = list(
        QuerySet(model_class).filter(id__in=ids, workspace_id=workspace_id)
        .values_list('id', flat=True)
    )

    cross_workspace_ids = [i for i in ids if i not in set(map(str, same_workspace_ids))]

    authorized_ids = set(map(str, same_workspace_ids))

    if cross_workspace_ids and auth_func is not None:
        cross_queryset = QuerySet(model_class).filter(id__in=cross_workspace_ids)
        authorized = auth_func(cross_queryset, workspace_id)
        authorized_ids.update(str(r.id) for r in authorized)

    return [i for i in ids if str(i) in authorized_ids]