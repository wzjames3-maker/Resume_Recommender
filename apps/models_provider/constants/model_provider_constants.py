# coding=utf-8
from enum import Enum

# 已裁剪 provider（对应 SDK 依赖已从 pyproject.toml 移除）：
# aliyun_bai_lian(dashscope) / anthropic(langchain-anthropic) / aws_bedrock(langchain-aws)
# gemini(langchain-google-genai) / local_model(torch+sentence-transformers) / ollama(langchain-ollama)
# tencent_cloud / tencent(tencentcloud-sdk) / volcanic_engine(volcengine) / wenxin(qianfan)
# xf(langchain-community) / xinference(xinference-client) / vllm(cohere) / minimax(dashscope)
# local_model 已删除（torch+sentence-transformers，本地推理运行时已移除）
from models_provider.impl.azure_model_provider.azure_model_provider import AzureModelProvider
from models_provider.impl.deepseek_model_provider.deepseek_model_provider import DeepSeekModelProvider
from models_provider.impl.docker_ai_model_provider.docker_ai_model_provider import DockerModelProvider
from models_provider.impl.kimi_model_provider.kimi_model_provider import KimiModelProvider
from models_provider.impl.openai_model_provider.openai_model_provider import OpenAIModelProvider
from models_provider.impl.regolo_model_provider.regolo_model_provider import RegoloModelProvider
from models_provider.impl.siliconCloud_model_provider.siliconCloud_model_provider import SiliconCloudModelProvider
from models_provider.impl.zhipu_model_provider.zhipu_model_provider import ZhiPuModelProvider


class ModelProvideConstants(Enum):
    model_azure_provider = AzureModelProvider()
    model_openai_provider = OpenAIModelProvider()
    model_docker_ai_provider = DockerModelProvider()
    model_kimi_provider = KimiModelProvider()
    model_zhipu_provider = ZhiPuModelProvider()
    model_deepseek_provider = DeepSeekModelProvider()
    model_siliconCloud_provider = SiliconCloudModelProvider()
    model_regolo_provider = RegoloModelProvider()
