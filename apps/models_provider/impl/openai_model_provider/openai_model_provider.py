# coding=utf-8
"""
    @project: maxkb
    @Author：虎
    @file： openai_model_provider.py
    @date：2024/3/28 16:26
    @desc:
"""
import os

from common.utils.common import get_file_content
from models_provider.base_model_provider import IModelProvider, ModelProvideInfo, ModelInfo, \
    ModelTypeConst, ModelInfoManage
from models_provider.impl.openai_model_provider.credential.embedding import OpenAIEmbeddingCredential
from models_provider.impl.openai_model_provider.credential.llm import OpenAILLMModelCredential
from models_provider.impl.openai_model_provider.credential.rerank import OpenAIRerankCredential
from models_provider.impl.openai_model_provider.model.embedding import OpenAIEmbeddingModel
from models_provider.impl.openai_model_provider.model.llm import OpenAIChatModel
from models_provider.impl.openai_model_provider.model.rerank import OpenAIRerankModel
from maxkb.conf import PROJECT_DIR
from django.utils.translation import gettext_lazy as _

openai_llm_model_credential = OpenAILLMModelCredential()
model_info_list = [
    ModelInfo('gpt-3.5-turbo', _('The latest gpt-3.5-turbo, updated with OpenAI adjustments'), ModelTypeConst.LLM,
              openai_llm_model_credential, OpenAIChatModel
              ),
    ModelInfo('gpt-4', _('Latest gpt-4, updated with OpenAI adjustments'), ModelTypeConst.LLM, openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-4o', _('The latest GPT-4o, cheaper and faster than gpt-4-turbo, updated with OpenAI adjustments'),
              ModelTypeConst.LLM, openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-4o-mini', _('The latest gpt-4o-mini, cheaper and faster than gpt-4o, updated with OpenAI adjustments'),
              ModelTypeConst.LLM, openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-4-turbo', _('The latest gpt-4-turbo, updated with OpenAI adjustments'), ModelTypeConst.LLM,
              openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-4-turbo-preview', _('The latest gpt-4-turbo-preview, updated with OpenAI adjustments'),
              ModelTypeConst.LLM, openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-3.5-turbo-0125',
              _('gpt-3.5-turbo snapshot on January 25, 2024, supporting context length 16,385 tokens'), ModelTypeConst.LLM,
              openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-3.5-turbo-1106',
              _('gpt-3.5-turbo snapshot on November 6, 2023, supporting context length 16,385 tokens'), ModelTypeConst.LLM,
              openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-3.5-turbo-0613',
              _('[Legacy] gpt-3.5-turbo snapshot on June 13, 2023, will be deprecated on June 13, 2024'),
              ModelTypeConst.LLM, openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-4o-2024-05-13',
              _('gpt-4o snapshot on May 13, 2024, supporting context length 128,000 tokens'),
              ModelTypeConst.LLM, openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-4-turbo-2024-04-09',
              _('gpt-4-turbo snapshot on April 9, 2024, supporting context length 128,000 tokens'),
              ModelTypeConst.LLM, openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-4-0125-preview', _('gpt-4-turbo snapshot on January 25, 2024, supporting context length 128,000 tokens'),
              ModelTypeConst.LLM, openai_llm_model_credential,
              OpenAIChatModel),
    ModelInfo('gpt-4-1106-preview', _('gpt-4-turbo snapshot on November 6, 2023, supporting context length 128,000 tokens'),
              ModelTypeConst.LLM, openai_llm_model_credential,
              OpenAIChatModel),
]
open_ai_embedding_credential = OpenAIEmbeddingCredential()
model_info_embedding_list = [
    ModelInfo('text-embedding-ada-002', '',
              ModelTypeConst.EMBEDDING, open_ai_embedding_credential,
              OpenAIEmbeddingModel),
    ModelInfo('text-embedding-3-small', '',
              ModelTypeConst.EMBEDDING, open_ai_embedding_credential,
              OpenAIEmbeddingModel),
    ModelInfo('text-embedding-3-large', '',
              ModelTypeConst.EMBEDDING, open_ai_embedding_credential,
              OpenAIEmbeddingModel),
    ModelInfo('BAAI/bge-large-zh-v1.5', _('BGE large Chinese embedding, OpenAI-compatible endpoint'),
              ModelTypeConst.EMBEDDING, open_ai_embedding_credential,
              OpenAIEmbeddingModel),
]

# 外部 OpenAI 兼容模型（SenseNova / SiliconFlow 等，api_base 由工作区管理员配置）
model_info_external_llm_list = [
    ModelInfo('sensenova-6.8-flash-lite', _('SenseNova 6.8 flash lite, OpenAI-compatible endpoint'),
              ModelTypeConst.LLM, openai_llm_model_credential, OpenAIChatModel),
]

open_ai_rerank_credential = OpenAIRerankCredential()
model_info_rerank_list = [
    ModelInfo('BAAI/bge-reranker-v2-m3', _('BGE reranker v2 m3, OpenAI-compatible rerank endpoint'),
              ModelTypeConst.RERANKER, open_ai_rerank_credential, OpenAIRerankModel),
]

model_info_manage = (
    ModelInfoManage.builder()
    .append_model_info_list(model_info_list)
    .append_default_model_info(ModelInfo('gpt-3.5-turbo', _('The latest gpt-3.5-turbo, updated with OpenAI adjustments'), ModelTypeConst.LLM,
                                         openai_llm_model_credential, OpenAIChatModel
                                         ))
    .append_model_info_list(model_info_embedding_list)
    .append_default_model_info(model_info_embedding_list[0])
    .append_model_info_list(model_info_external_llm_list)
    .append_model_info_list(model_info_rerank_list)
    .build()
)


class OpenAIModelProvider(IModelProvider):

    def get_model_info_manage(self):
        return model_info_manage

    def get_model_provide_info(self):
        return ModelProvideInfo(provider='model_openai_provider', name='OpenAI', icon=get_file_content(
            os.path.join(PROJECT_DIR, "apps", 'models_provider', 'impl', 'openai_model_provider', 'icon',
                         'openai_icon_svg')))
