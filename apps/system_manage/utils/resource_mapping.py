# coding=utf-8
"""
    @project: maxkb
    @Author：虎
    @file： resource_mapping.py
    @date：2026/8/13
    @desc: resource mapping helpers for non-workflow resources
"""
from functools import reduce

from django.db.models import QuerySet

from system_manage.models.resource_mapping import ResourceMapping

application_instance_field_call_dict = {
    "APPLICATION": [
        lambda instance: instance.application_ids or [],
    ],
    "MODEL": [
        lambda instance: [instance.model_id] if instance.model_id else [],
        lambda instance: [instance.long_term_model_id] if instance.long_term_model_id else [],
        lambda instance: [instance.tts_model_id] if instance.tts_model_id else [],
        lambda instance: [instance.stt_model_id] if instance.stt_model_id else [],
    ],
}

knowledge_instance_field_call_dict = {
    "MODEL": [lambda instance: [instance.embedding_model_id] if instance.embedding_model_id else []],
}


def get_instance_resource(instance, source_type, source_id, instance_field_call_dict):
    response = []
    for target_type, call_list in instance_field_call_dict.items():
        target_id_list = reduce(lambda x, y: [*x, *y], [call(instance) for call in call_list], [])
        if target_id_list:
            for target_id in target_id_list:
                response.append(
                    ResourceMapping(
                        source_type=source_type, target_type=target_type, source_id=source_id, target_id=target_id
                    )
                )
    return response


def save_resource_mapping(source_type, source_id, other_resource_mapping=None):
    if other_resource_mapping is None:
        other_resource_mapping = []
    QuerySet(ResourceMapping).filter(source_type=source_type, source_id=source_id).delete()
    if other_resource_mapping:
        QuerySet(ResourceMapping).bulk_create(
            {(str(item.target_type) + str(item.target_id)): item for item in other_resource_mapping}.values()
        )
