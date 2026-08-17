import uuid_utils.compat as uuid
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from application.models import Application, ApplicationFolder
from knowledge.models import Document, File, Knowledge, KnowledgeFolder, Paragraph
from models_provider.models import Model
from system_manage.models import WorkspaceOffboard, WorkspaceUserResourcePermission
from system_manage.models.resource_mapping import ResourceMapping
from system_manage.services.workspace_offboarding import WorkspaceOffboardingService, offboard_workspace
from users.models import User


class WorkspaceOffboardingServiceTests(TestCase):
    def setUp(self):
        self.workspace = "workspace-core-offboard"
        self.other_workspace = "workspace-core-other"
        self.user = User.objects.create(
            username="core-offboard-" + uuid.uuid7().hex[:8],
            nick_name="core-offboard-" + uuid.uuid7().hex[:8],
            password="p",
            role="ADMIN",
        )

    def _create_workspace(self, workspace_id):
        app_folder = ApplicationFolder.objects.create(
            id="app-folder-" + workspace_id, name="应用文件夹", workspace_id=workspace_id
        )
        application = Application.objects.create(
            workspace_id=workspace_id, folder=app_folder, name="租户应用", desc="测试应用"
        )
        ApplicationFolder.objects.create(
            id="app-child-" + workspace_id, name="应用子文件夹", workspace_id=workspace_id, parent=app_folder
        )
        knowledge_folder = KnowledgeFolder.objects.create(
            id="kb-folder-" + workspace_id, name="知识文件夹", workspace_id=workspace_id
        )
        KnowledgeFolder.objects.create(
            id="kb-child-" + workspace_id, name="知识子文件夹", workspace_id=workspace_id, parent=knowledge_folder
        )
        knowledge = Knowledge.objects.create(
            workspace_id=workspace_id, folder=knowledge_folder, name="租户知识库", desc="测试知识库"
        )
        document = Document.objects.create(knowledge=knowledge, name="tenant.txt", char_length=12)
        paragraph = Paragraph.objects.create(
            document=document, knowledge=knowledge, content="跨域隔离内容", title="标题"
        )
        stored_file = File(
            id=uuid.uuid7(), file_name="tenant.txt", source_type="DOCUMENT", source_id=str(document.id), loid=1
        )
        stored_file.save(bytea=b"tenant-file")
        model = Model.objects.create(
            id=uuid.uuid7(), name="tenant-model", status="SUCCESS", model_type="LLM",
            model_name="test", provider="test", credential="secret-credential", workspace_id=workspace_id,
        )
        permission = WorkspaceUserResourcePermission.objects.create(
            workspace_id=workspace_id, user=self.user, auth_target_type="APPLICATION",
            target=str(application.id), permission_list=["READ"],
        )
        ResourceMapping.objects.create(
            source_type="APPLICATION", target_type="KNOWLEDGE", source_id=str(application.id), target_id=str(knowledge.id)
        )
        return {
            "application": application,
            "knowledge": knowledge,
            "document": document,
            "paragraph": paragraph,
            "file": stored_file,
            "model": model,
            "permission": permission,
        }

    def test_plan_export_and_purge_are_workspace_scoped(self):
        owned = self._create_workspace(self.workspace)
        other = self._create_workspace(self.other_workspace)
        plan = WorkspaceOffboardingService.plan(self.workspace)
        self.assertEqual(plan["core"]["counts"]["applications"], 1)
        self.assertEqual(plan["core"]["counts"]["knowledge"], 1)
        self.assertFalse(plan["can_offboard"])

        payload = WorkspaceOffboardingService.export_data(self.workspace, plan)
        self.assertEqual(payload["workspace_id"], self.workspace)
        self.assertEqual(payload["applications"][0]["name"], "租户应用")
        self.assertNotIn("credential", payload["models"][0])
        self.assertTrue(Application.objects.filter(id=owned["application"].id).exists())

        result = offboard_workspace(self.workspace, user_id=self.user.id, force=True, include_export=True)
        self.assertEqual(result["status"], "OFFBOARDED")
        self.assertEqual(result["export"]["workspace_id"], self.workspace)
        self.assertEqual(Application.objects.filter(workspace_id=self.workspace).count(), 0)
        self.assertEqual(Knowledge.objects.filter(workspace_id=self.workspace).count(), 0)
        self.assertEqual(Document.objects.filter(id=owned["document"].id).count(), 0)
        self.assertEqual(Paragraph.objects.filter(id=owned["paragraph"].id).count(), 0)
        self.assertEqual(File.objects.filter(id=owned["file"].id).count(), 0)
        self.assertEqual(Model.objects.filter(workspace_id=self.workspace).count(), 0)
        self.assertEqual(WorkspaceUserResourcePermission.objects.filter(workspace_id=self.workspace).count(), 0)
        self.assertEqual(ResourceMapping.objects.filter(source_id=str(owned["application"].id)).count(), 0)
        self.assertTrue(Application.objects.filter(id=other["application"].id).exists())
        self.assertTrue(Knowledge.objects.filter(id=other["knowledge"].id).exists())
        self.assertTrue(File.objects.filter(id=other["file"].id).exists())
        self.assertTrue(Model.objects.filter(id=other["model"].id).exists())

    def test_offboard_rolls_back_hr_and_core_rows_when_core_delete_fails(self):
        self._create_workspace(self.workspace)
        from hr.models import Candidate, HrOffboard

        Candidate.objects.create(workspace_id=self.workspace, name="HR 候选人")
        with patch.object(WorkspaceOffboardingService, "_delete_core", side_effect=RuntimeError("simulated failure")):
            with self.assertRaises(RuntimeError):
                offboard_workspace(self.workspace, user_id=self.user.id, force=True)
        self.assertTrue(Application.objects.filter(workspace_id=self.workspace).exists())
        self.assertTrue(Candidate.objects.filter(workspace_id=self.workspace).exists())
        self.assertFalse(WorkspaceOffboard.objects.filter(workspace_id=self.workspace).exists())
        self.assertFalse(HrOffboard.objects.filter(workspace_id=self.workspace).exists())

    def test_default_workspace_is_protected_and_reentry_is_idempotent(self):
        blocked = WorkspaceOffboardingService.offboard("default", user_id=self.user.id, force=True)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertFalse(WorkspaceOffboard.objects.filter(workspace_id="default").exists())

        result = offboard_workspace(self.workspace, user_id=self.user.id, force=True)
        self.assertEqual(result["status"], "OFFBOARDED")
        repeat = offboard_workspace(self.workspace, user_id=self.user.id, force=True)
        self.assertEqual(repeat["status"], "ALREADY_OFFBOARDED")
        self.assertEqual(WorkspaceOffboard.objects.filter(workspace_id=self.workspace).count(), 1)


class WorkspaceOffboardingApiTests(TestCase):
    def setUp(self):
        self.workspace = "workspace-core-api"
        self.admin = User.objects.create(
            username="core-api-" + uuid.uuid7().hex[:8],
            nick_name="core-api-" + uuid.uuid7().hex[:8],
            password="p",
            role="ADMIN",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_system_api_denies_non_admin(self):
        denied_user = User.objects.create(
            username="core-api-denied-" + uuid.uuid7().hex[:8],
            nick_name="core-api-denied-" + uuid.uuid7().hex[:8],
            password="p",
            role="USER",
        )
        denied_client = APIClient()
        denied_client.force_authenticate(user=denied_user)
        response = denied_client.get(f"/admin/api/workspace/{self.workspace}/offboarding/preview")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 403)

    def test_system_api_preview_and_purge(self):
        Candidate = __import__("hr.models", fromlist=["Candidate"]).Candidate
        Candidate.objects.create(workspace_id=self.workspace, name="Core API")
        base = f"/admin/api/workspace/{self.workspace}/offboarding"
        preview = self.client.get(base + "/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["data"]["status"], "DRY_RUN")
        self.assertEqual(preview.json()["data"]["counts"]["core"]["applications"], 0)
        purge = self.client.post(
            base, {"confirm_workspace_id": self.workspace, "export": True}, format="json"
        )
        self.assertEqual(purge.status_code, 200)
        self.assertEqual(purge.json()["data"]["status"], "OFFBOARDED")
        self.assertEqual(purge.json()["data"]["export"]["workspace_id"], self.workspace)
        self.assertEqual(Candidate.objects.filter(workspace_id=self.workspace).count(), 0)
