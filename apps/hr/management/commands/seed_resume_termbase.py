# coding=utf-8
"""
    @project: MaxKB
    @file： seed_resume_termbase.py
    @date：2026/8/16
    @desc：向简历语义索引知识库幂等写入技能同义词词条（Termbase）。
          KeywordsSearch().handle 内部已按 knowledge_id 自动读取 Termbase（pg_vector.py:294-298），
          入库侧 _batch_save 同样生效——检索代码零改动。
          注意：仅插入词条不会改变已有 search_vector；需配合 reindex_resume_knowledge 全量重嵌。
          注意：_sparse_query（resume_search.py）硬编码停用词（经验/工作/熟悉/精通等），词条设计需避开。
          用法：<env> .venv/bin/python apps/manage.py seed_resume_termbase [--workspace ws_id]
"""
import uuid_utils.compat as uuid
from django.core.management.base import BaseCommand
from django.db.models import QuerySet

from knowledge.models import Knowledge, Termbase

from hr.services.resume_index import _KNOWLEDGE_NAME, get_resume_knowledge

# 词条源：skill_alias 别名（变体）→ 规范形；另附高频规范技能词（查询侧到词条的直接命中）
_EXTRA_TERMS = [
    "java", "python", "go", "typescript", "javascript", "html", "css", "react", "vue",
    "node", "springboot", "springcloud", "mysql", "postgresql", "redis", "mongodb",
    "elasticsearch", "kafka", "rabbitmq", "nginx", "linux", "git", "maven", "gradle",
    "jenkins", "docker", "kubernetes", "微服务", "分布式", "云原生", "restful",
    "pytorch", "tensorflow", "机器学习", "深度学习", "nlp", "数据分析", "spark",
    "flink", "hadoop", "hive", "c++", "c#", "flutter", "android", "ios", "sql",
    "excel", "ppt", "selenium", "jmeter", "自动化测试", "接口测试", "单元测试",
    "项目管理", "阿里云", "aws",
]


class Command(BaseCommand):
    help = "向简历语义索引知识库幂等写入技能词条（Termbase）"

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, default=None, help="仅处理指定工作区（缺省全部）")

    def handle(self, *args, **options):
        workspaces = [options["workspace"]] if options.get("workspace") else list(
            QuerySet(Knowledge).filter(name=_KNOWLEDGE_NAME).values_list("workspace_id", flat=True).distinct()
        )
        total = 0
        for workspace_id in workspaces:
            knowledge = get_resume_knowledge(workspace_id)
            if knowledge is None:
                self.stdout.write(self.style.WARNING(f"workspace {workspace_id}: 简历知识库不存在，跳过"))
                continue
            terms = set(_EXTRA_TERMS)
            for alias, canonical in _ALIAS_TERMS():
                terms.add(alias)
                terms.add(canonical)
            existing = set(
                QuerySet(Termbase).filter(knowledge_id=knowledge.id).values_list("content", flat=True)
            )
            to_create = terms - existing
            QuerySet(Termbase).bulk_create(
                [Termbase(id=uuid.uuid7(), knowledge_id=knowledge.id, content=t) for t in sorted(to_create)]
            ) if to_create else None
            self.stdout.write(
                self.style.SUCCESS(
                    f"workspace {workspace_id}: terms {len(terms)} (existing {len(existing)}, inserted {len(to_create)})"
                )
            )
            total += len(to_create)
        self.stdout.write(self.style.SUCCESS(f"done, total inserted: {total}"))


def _ALIAS_TERMS():
    """从 skill_alias.json 取 (变体, 规范形) 对；变体与规范形都进词条，查询/入库双向可命中。"""
    import json
    import os

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "data", "skill_alias.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return list(data.items())
