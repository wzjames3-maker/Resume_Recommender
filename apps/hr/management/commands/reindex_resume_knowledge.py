# coding=utf-8
"""
    @project: MaxKB
    @file： reindex_resume_knowledge.py
    @date：2026/8/16
    @desc：简历语义索引全量重嵌（T2 存量 chunks 标题前缀 + T6 Termbase 词条 一次生效）。
          逐文档 embedding_by_document.delay（QueueOnce 防重）。
          注意：重嵌窗口 drop_knowledge_index 期间检索降级为 seq scan（不失败），建议低峰执行；
          本项目纪律：不运行真实模型，本命令由项目方在真实环境执行。
          用法：<env> .venv/bin/python apps/manage.py reindex_resume_knowledge [--workspace ws_id] [--dry-run]
"""
from django.core.management.base import BaseCommand
from django.db.models import QuerySet

from knowledge.models import Document, Knowledge
from knowledge.task.embedding import embedding_by_document


class Command(BaseCommand):
    help = "简历语义索引全量重嵌（重嵌后 title 前缀 chunks 与 Termbase 分词生效）"

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, default=None, help="仅处理指定工作区（缺省全部简历知识库）")
        parser.add_argument("--dry-run", action="store_true", help="只打印将重嵌的文档数，不入队")

    def handle(self, *args, **options):
        dry_run = options.get("dry_run")
        workspace_id = options.get("workspace")
        if workspace_id:
            from hr.services.resume_index import get_resume_knowledge

            knowledge = get_resume_knowledge(workspace_id)
            if knowledge is None:
                self.stderr.write(f"workspace {workspace_id}: 简历知识库不存在")
                return
            knowledge_ids = [knowledge.id]
        else:
            knowledge_ids = list(
                QuerySet(Knowledge).filter(name="简历语义索引").values_list("id", flat=True)
            )
        doc_ids = list(
            QuerySet(Document).filter(knowledge_id__in=knowledge_ids).values_list("id", flat=True)
        )
        self.stdout.write(self.style.WARNING(f"documents to re-embed: {len(doc_ids)}"))
        if dry_run:
            return
        queued = 0
        for doc_id in doc_ids:
            doc = QuerySet(Document).filter(id=doc_id).first()
            knowledge = QuerySet(Knowledge).filter(id=doc.knowledge_id).first()
            if knowledge is None or knowledge.embedding_model_id is None:
                self.stderr.write(f"doc {doc_id}: embedding model missing, skipped")
                continue
            embedding_by_document.delay(str(doc_id), str(knowledge.embedding_model_id))
            queued += 1
        self.stdout.write(self.style.SUCCESS(f"queued {queued} documents"))
