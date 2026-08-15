import unittest.mock as mock

import uuid_utils.compat as uuid
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase
from django.db.migrations.executor import MigrationExecutor

from common.exception.app_exception import AppApiException
from models_provider.constants.model_provider_constants import ModelProvideConstants
from models_provider.impl.openai_model_provider.credential.rerank import OpenAIRerankCredential
from models_provider.impl.openai_model_provider.model.rerank import OpenAIRerankModel
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

class ExternalModelRegistrationTests(SimpleTestCase):
    def setUp(self):
        self.provider = ModelProvideConstants.model_openai_provider.value

    def test_sensenova_llm_registered(self):
        names = [item.get('name') for item in self.provider.get_model_list('LLM')]
        self.assertIn('sensenova-6.8-flash-lite', names)

    def test_bge_embedding_registered(self):
        names = [item.get('name') for item in self.provider.get_model_list('EMBEDDING')]
        self.assertIn('BAAI/bge-large-zh-v1.5', names)

    def test_reranker_registered_and_type_listed(self):
        names = [item.get('name') for item in self.provider.get_model_list('RERANKER')]
        self.assertIn('BAAI/bge-reranker-v2-m3', names)
        type_list = [item.get('value') for item in self.provider.get_model_type_list()]
        self.assertIn('RERANKER', type_list)

    def test_rerank_credential_resolved(self):
        credential = self.provider.get_model_credential('RERANKER', 'BAAI/bge-reranker-v2-m3')
        self.assertIsInstance(credential, OpenAIRerankCredential)

    def test_llm_and_embedding_credential_still_shared(self):
        llm_credential = self.provider.get_model_credential('LLM', 'sensenova-6.8-flash-lite')
        embedding_credential = self.provider.get_model_credential('EMBEDDING', 'BAAI/bge-large-zh-v1.5')
        from models_provider.impl.openai_model_provider.credential.llm import OpenAILLMModelCredential
        from models_provider.impl.openai_model_provider.credential.embedding import OpenAIEmbeddingCredential
        self.assertIsInstance(llm_credential, OpenAILLMModelCredential)
        self.assertIsInstance(embedding_credential, OpenAIEmbeddingCredential)


class RerankCredentialTests(SimpleTestCase):
    def test_required_fields(self):
        form_list = OpenAIRerankCredential().to_form_list()
        fields = {item.get('field') for item in form_list}
        self.assertIn('api_base', fields)
        self.assertIn('api_key', fields)

    def test_encryption_dict_masks_api_key(self):
        encrypted = OpenAIRerankCredential().encryption_dict(
            {'api_base': 'https://api.siliconflow.cn/v1', 'api_key': 'sk-1234567890abcdef'})
        self.assertNotEqual(encrypted.get('api_key'), 'sk-1234567890abcdef')
        self.assertIn('***', encrypted.get('api_key'))

    def test_params_form_has_top_n_default(self):
        form_list = OpenAIRerankCredential().get_model_params_setting_form('BAAI/bge-reranker-v2-m3').to_form_list()
        top_n_item = [item for item in form_list if item.get('field') == 'top_n'][0]
        self.assertEqual(top_n_item.get('default_value'), 3)


class OpenAIRerankModelTests(SimpleTestCase):
    def test_rerank_parses_and_sorts(self):
        with mock.patch('models_provider.impl.openai_model_provider.model.rerank.requests.post') as mocked_post:
            mocked_post.return_value.status_code = 200
            mocked_post.return_value.json.return_value = {
                'results': [
                    {'index': 0, 'relevance_score': 0.5},
                    {'index': 1, 'relevance_score': 0.9},
                    {'index': 2, 'relevance_score': 0.7},
                ]
            }
            model = OpenAIRerankModel(api_key='sk-test', base_url='https://api.siliconflow.cn/v1/',
                                      model_name='BAAI/bge-reranker-v2-m3', top_n=2)
            result = model.rerank('query', ['doc1', 'doc2', 'doc3'])
        self.assertEqual(result, [{'index': 1, 'relevance_score': 0.9}, {'index': 2, 'relevance_score': 0.7}])
        self.assertEqual(mocked_post.call_args.args[0], 'https://api.siliconflow.cn/v1/rerank')
        request_body = mocked_post.call_args.kwargs['json']
        self.assertEqual(request_body['model'], 'BAAI/bge-reranker-v2-m3')
        self.assertEqual(request_body['query'], 'query')
        self.assertEqual(request_body['documents'], ['doc1', 'doc2', 'doc3'])
        self.assertEqual(request_body['top_n'], 2)
        self.assertEqual(mocked_post.call_args.kwargs['headers']['Authorization'], 'Bearer sk-test')

    def test_rerank_without_top_n_uses_model_default(self):
        with mock.patch('models_provider.impl.openai_model_provider.model.rerank.requests.post') as mocked_post:
            mocked_post.return_value.status_code = 200
            mocked_post.return_value.json.return_value = {'results': [{'index': 0, 'relevance_score': 0.8}]}
            model = OpenAIRerankModel(api_key='sk-test', base_url='https://api.siliconflow.cn/v1',
                                      model_name='BAAI/bge-reranker-v2-m3', top_n=5)
            model.rerank('query', ['doc1'])
        self.assertEqual(mocked_post.call_args.kwargs['json']['top_n'], 5)

    def test_rerank_http_error_raises(self):
        with mock.patch('models_provider.impl.openai_model_provider.model.rerank.requests.post') as mocked_post:
            mocked_post.return_value.status_code = 401
            mocked_post.return_value.text = 'unauthorized'
            model = OpenAIRerankModel(api_key='k', base_url='https://x/v1', model_name='m')
            with self.assertRaisesRegex(Exception, '401'):
                model.rerank('query', ['doc1'])

    def test_rerank_empty_documents_returns_empty(self):
        model = OpenAIRerankModel(api_key='k', base_url='https://x/v1', model_name='m')
        self.assertEqual(model.rerank('query', []), [])

    def test_new_instance_passes_credential_and_top_n(self):
        model = OpenAIRerankModel.new_instance('RERANKER', 'BAAI/bge-reranker-v2-m3',
                                               {'api_key': 'k', 'api_base': 'https://x/v1/'}, top_n=5)
        self.assertEqual(model.api_key, 'k')
        self.assertEqual(model.base_url, 'https://x/v1')
        self.assertEqual(model.model_name, 'BAAI/bge-reranker-v2-m3')
        self.assertEqual(model.top_n, 5)


class ExternalModelInstanceTests(SimpleTestCase):
    def setUp(self):
        self.provider = ModelProvideConstants.model_openai_provider.value

    def test_sensenova_llm_instance_construction(self):
        model = self.provider.get_model('LLM', 'sensenova-6.8-flash-lite',
                                        {'api_key': 'sk-test', 'api_base': 'https://token.sensenova.cn/v1'},
                                        streaming=False)
        self.assertEqual(model.model_name, 'sensenova-6.8-flash-lite')

    def test_bge_embedding_instance_construction(self):
        model = self.provider.get_model('EMBEDDING', 'BAAI/bge-large-zh-v1.5',
                                        {'api_key': 'sk-test', 'api_base': 'https://api.siliconflow.cn/v1'})
        self.assertEqual(model.model_name, 'BAAI/bge-large-zh-v1.5')
