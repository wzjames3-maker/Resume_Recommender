# coding=utf-8
from enum import Enum

# 已裁剪 provider（对应 SDK 依赖已从 pyproject.toml 移除）：
# aliyun_bai_lian(dashscope) / anthropic(langchain-anthropic) / aws_bedrock(langchain-aws)
# gemini(langchain-google-genai) / local_model(torch+sentence-transformers) / ollama(langchain-ollama)
# tencent_cloud / tencent(tencentcloud-sdk) / volcanic_engine(volcengine) / wenxin(qianfan)
# xf(langchain-community) / xinference(xinference-client) / vllm(cohere) / minimax(dashscope)
# local_model 已删除（torch+sentence-transformers，本地推理运行时已移除）
# 本地精简内核仅保留 OpenAI 兼容协议的 LLM 与 Embedding
from models_provider.impl.openai_model_provider.openai_model_provider import OpenAIModelProvider


class ModelProvideConstants(Enum):
    model_openai_provider = OpenAIModelProvider()
