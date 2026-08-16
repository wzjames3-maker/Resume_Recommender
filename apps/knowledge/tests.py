import uuid_utils.compat as uuid
from django.test import TestCase

from unittest.mock import patch

from common.exception.app_exception import AppApiException
from knowledge.models import (
    Document,
    Knowledge,
    KnowledgeFolder,
    KnowledgeScope,
    KnowledgeType,
    Paragraph,
)
from knowledge.serializers.knowledge import KnowledgeSerializer
from models_provider.models import Model
from users.models import User


class EmbeddingDispatchLogTests(TestCase):
    """P2-7：embedding_by_knowledge 派发失败不再静默——记录失败文档（此前 except: pass 无迹可查）。"""

    def setUp(self):
        KnowledgeFolder.objects.get_or_create(id="default", defaults={"name": "default", "workspace_id": "default"})
        self.model = Model.objects.create(
            id=uuid.uuid7(), name="bge-test", status="SUCCESS", model_type="EMBEDDING",
            model_name="BAAI/bge-large-zh-v1.5", provider="model_openai_provider",
            credential="{}", meta={}, workspace_id="default",
        )
        self.knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), name="k-emb", workspace_id="default", embedding_model_id=self.model.id,
            user_id=self.user.id if hasattr(self, "user") else None, type=KnowledgeType.BASE.value,
            scope=KnowledgeScope.WORKSPACE.value, folder_id="default",
        )
        self.document = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=self.knowledge.id, name="d.txt",
            char_length=1, user_id=None,
        )

    def test_dispatch_failure_logged(self):
        from knowledge.task import embedding as emb_task

        with patch("knowledge.task.embedding.embedding_by_document.delay", side_effect=Exception("broker down")), \
                patch("knowledge.task.embedding.maxkb_logger.error") as m_err:
            emb_task.embedding_by_knowledge(str(self.knowledge.id), str(self.model.id))
        self.assertTrue(m_err.called)
        self.assertIn(str(self.document.id), str(m_err.call_args))


class CreateKnowledgeIndexTests(TestCase):
    """P2-8：索引 DDL 幂等（IF NOT EXISTS / IF EXISTS），防并发向量化收尾竞态。"""

    def test_create_index_uses_if_not_exists(self):
        from knowledge.serializers.common import create_knowledge_index

        with patch("knowledge.serializers.common.sql_execute", side_effect=[[], [{"dims": 1024}]]), \
                patch("knowledge.serializers.common.update_execute") as m_upd:
            create_knowledge_index(knowledge_id=uuid.uuid7())
        self.assertIn("CREATE INDEX IF NOT EXISTS", m_upd.call_args[0][0])

    def test_drop_index_uses_if_exists(self):
        from knowledge.serializers.common import drop_knowledge_index

        with patch("knowledge.serializers.common.sql_execute", return_value=[{"indexname": "x"}]), \
                patch("knowledge.serializers.common.update_execute") as m_upd:
            drop_knowledge_index(knowledge_id=uuid.uuid7())
        self.assertIn("DROP INDEX IF EXISTS", m_upd.call_args[0][0])

class DocumentSyncTransactionTests(TestCase):
    """K2：Sync.sync 网络抓取移出事务——成功/失败路径行为保持（结构重排回归）。"""

    def setUp(self):
        KnowledgeFolder.objects.get_or_create(id="default", defaults={"name": "default", "workspace_id": "default"})
        self.model = Model.objects.create(
            id=uuid.uuid7(), name="bge-test", status="SUCCESS", model_type="EMBEDDING",
            model_name="BAAI/bge-large-zh-v1.5", provider="model_openai_provider",
            credential="{}", meta={}, workspace_id="default",
        )
        self.user = User.objects.create(username="sync-" + uuid.uuid7().hex[:8], nick_name="s", password="p", role="ADMIN")
        self.knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), name="k-sync", workspace_id="default", embedding_model_id=self.model.id,
            user_id=self.user.id, type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value,
            folder_id="default",
        )
        self.document = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=self.knowledge.id, name="web.md",
            char_length=0, user_id=self.user.id, type=KnowledgeType.WEB.value,
            meta={"source_url": "http://example.com/page", "selector": ""},
        )

    def _sync(self):
        from knowledge.serializers.document import DocumentSerializers

        return DocumentSerializers.Sync(
            data={"knowledge_id": str(self.knowledge.id), "document_id": str(self.document.id)}
        ).sync()

    @patch("knowledge.serializers.document.Fork")
    @patch("knowledge.serializers.document.embedding_by_document.delay")
    def test_sync_success_creates_paragraphs(self, mock_delay, mock_fork):
        mock_fork.return_value.fork.return_value = type(
            "FakeResponse", (), {"status": 200, "content": "# 标题\n正文内容段落"})()
        self._sync()
        self.assertGreaterEqual(Paragraph.objects.filter(document_id=self.document.id).count(), 1)
        self.document.refresh_from_db()
        self.assertGreater(self.document.char_length, 0)
        mock_delay.assert_called()

    @patch("knowledge.serializers.document.Fork")
    def test_sync_fetch_failure_marks_state(self, mock_fork):
        mock_fork.return_value.fork.side_effect = Exception("network down")
        self._sync()  # 不抛异常（异常路径被捕获，状态置 FAILURE）
        self.assertEqual(Paragraph.objects.filter(document_id=self.document.id).count(), 0)

    @patch("knowledge.serializers.document.Fork")
    def test_sync_non_200_marks_failure(self, mock_fork):
        mock_fork.return_value.fork.return_value = type(
            "FakeResponse", (), {"status": 500, "content": ""})()
        self._sync()
        self.assertEqual(Paragraph.objects.filter(document_id=self.document.id).count(), 0)



class WorkflowKnowledgeRejectionTests(TestCase):
    def setUp(self):
        KnowledgeFolder.objects.get_or_create(id="default", defaults={"name": "root", "workspace_id": "default"})
        self.knowledge = Knowledge.objects.create(
            id=uuid.uuid7(),
            name="legacy-workflow-kb",
            desc="",
            type=4,
            workspace_id="default",
            user_id=None,
            meta={"disabled_reason": "workflow_knowledge_removed_by_local_core"},
        )

    def test_operate_rejects_workflow_knowledge(self):
        serializer = KnowledgeSerializer.Operate(
            data={"user_id": str(uuid.uuid7()), "workspace_id": "default", "knowledge_id": str(self.knowledge.id)}
        )
        with self.assertRaisesRegex(AppApiException, "not supported"):
            serializer.is_valid(raise_exception=True)

    def test_hit_test_rejects_workflow_knowledge(self):
        serializer = KnowledgeSerializer.HitTest(
            data={
                "workspace_id": "default",
                "knowledge_id": str(self.knowledge.id),
                "query_text": "q",
                "top_number": 3,
                "similarity": 0.6,
                "search_mode": "embedding",
            }
        )
        with self.assertRaisesRegex(AppApiException, "not supported"):
            serializer.is_valid(raise_exception=True)
