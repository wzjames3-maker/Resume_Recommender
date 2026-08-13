import uuid_utils.compat as uuid
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase
from django.db.migrations.executor import MigrationExecutor

from common.exception.app_exception import AppApiException
from models_provider.tools import get_provider


class ProviderCompatibilityTests(SimpleTestCase):
    def test_removed_provider_has_readable_error(self):
        with self.assertRaisesRegex(AppApiException, "model_local_provider"):
            get_provider("model_local_provider")


class ProviderDisableMigrationTests(TransactionTestCase):
    migrate_from = [("models_provider", "0001_initial")]
    migrate_to = [("models_provider", "0002_disable_unsupported_providers")]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")

    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        self.old_apps = self.executor.loader.project_state(self.migrate_from).apps

    def tearDown(self):
        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)

    def test_migration_disables_unsupported_provider(self):
        OldModel = self.old_apps.get_model("models_provider", "Model")
        model_id = uuid.uuid7()
        OldModel.objects.create(
            id=model_id,
            name="legacy-embedding",
            status="SUCCESS",
            model_type="EMBEDDING",
            model_name="maxkb-embedding",
            provider="model_local_provider",
            credential="encrypted-credential",
            meta={},
            workspace_id="default",
        )

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        NewModel = new_apps.get_model("models_provider", "Model")
        model = NewModel.objects.get(id=model_id)

        self.assertEqual(model.status, "ERROR")
        self.assertEqual(model.meta["disabled_reason"], "provider_removed_by_local_core")

    def test_migration_keeps_openai_provider_untouched(self):
        OldModel = self.old_apps.get_model("models_provider", "Model")
        model_id = uuid.uuid7()
        OldModel.objects.create(
            id=model_id,
            name="gpt-4o",
            status="SUCCESS",
            model_type="LLM",
            model_name="gpt-4o",
            provider="model_openai_provider",
            credential="encrypted-credential",
            meta={},
            workspace_id="default",
        )

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        NewModel = new_apps.get_model("models_provider", "Model")
        model = NewModel.objects.get(id=model_id)

        self.assertEqual(model.status, "SUCCESS")
        self.assertNotIn("disabled_reason", model.meta or {})