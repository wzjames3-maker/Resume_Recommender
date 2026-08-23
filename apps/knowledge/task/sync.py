# coding=utf-8
"""
@project: MaxKB
@Author：虎
@file： sync.py
@date：2024/8/20 21:37
@desc:
"""

import traceback
from typing import List

from celery_once import QueueOnce
from common.utils.fork import Fork, ForkManage
from common.utils.logger import maxkb_logger
from django.utils.translation import gettext_lazy as _
from ops import celery_app


# 与 embedding 任务一致：bind + max_retries 指数退避重试，acks_late + reject_on_worker_lost
# 保证 worker 崩溃后消息重新投递，不再出现 STARTED 永久卡死。


@celery_app.task(
    base=QueueOnce,
    once={"keys": ["knowledge_id"]},
    name="celery:sync_web_knowledge",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def sync_web_knowledge(self, knowledge_id: str, user_id, url: str, selector: str):
    from knowledge.task.handler import get_save_handler

    try:
        maxkb_logger.info(
            _("Start--->Start synchronization web knowledge base:{knowledge_id}").format(knowledge_id=knowledge_id)
        )
        ForkManage(url, selector.split(" ") if selector is not None else []).fork(
            2, set(), get_save_handler(knowledge_id, user_id, selector)
        )

        maxkb_logger.info(
            _("End--->End synchronization web knowledge base:{knowledge_id}").format(knowledge_id=knowledge_id)
        )
    except Exception as e:
        maxkb_logger.error(
            _("Synchronize web knowledge base:{knowledge_id} error{error}{traceback}").format(
                knowledge_id=knowledge_id, error=str(e), traceback=traceback.format_exc()
            )
        )
        raise self.retry(exc=e, countdown=min(60 * 2 ** self.request.retries, 600))


@celery_app.task(
    base=QueueOnce,
    once={"keys": ["knowledge_id"]},
    name="celery:sync_replace_web_knowledge",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def sync_replace_web_knowledge(self, knowledge_id: str, user_id, url: str, selector: str):
    from knowledge.task.handler import get_sync_handler

    try:
        maxkb_logger.info(
            _("Start--->Start synchronization web knowledge base:{knowledge_id}").format(knowledge_id=knowledge_id)
        )
        ForkManage(url, selector.split(" ") if selector is not None else []).fork(
            2, set(), get_sync_handler(knowledge_id, user_id)
        )
        maxkb_logger.info(
            _("End--->End synchronization web knowledge base:{knowledge_id}").format(knowledge_id=knowledge_id)
        )
    except Exception as e:
        maxkb_logger.error(
            _("Synchronize web knowledge base:{knowledge_id} error{error}{traceback}").format(
                knowledge_id=knowledge_id, error=str(e), traceback=traceback.format_exc()
            )
        )
        raise self.retry(exc=e, countdown=min(60 * 2 ** self.request.retries, 600))


@celery_app.task(name="celery:sync_web_document", bind=True, max_retries=3, acks_late=True, reject_on_worker_lost=True)
def sync_web_document(self, knowledge_id, user_id, source_url_list: List[str], selector: str):
    from knowledge.task.handler import get_sync_web_document_handler

    try:
        handler = get_sync_web_document_handler(knowledge_id, user_id)
        for source_url in source_url_list:
            try:
                result = Fork(base_fork_url=source_url, selector_list=selector.split(" ")).fork()
                handler(source_url, selector, result)
            except Exception:
                pass
    except Exception as e:
        raise self.retry(exc=e, countdown=min(60 * 2 ** self.request.retries, 600))
