# coding=utf-8
"""
    @project: maxkb
    @Author：虎
    @file： rerank.py
    @date：2026/8/15
    @desc: OpenAI 兼容协议的 Rerank 模型（SiliconFlow 等 /v1/rerank 端点）
"""
from typing import Dict, List

import requests

from models_provider.base_model_provider import MaxKBBaseModel


class OpenAIRerankModel(MaxKBBaseModel):
    model_name: str

    def __init__(self, api_key, base_url, model_name: str, top_n: int = None, timeout: int = 60):
        self.api_key = api_key
        self.base_url = str(base_url).rstrip('/')
        self.model_name = model_name
        self.top_n = top_n
        self.timeout = timeout

    def is_cache_model(self):
        return False

    @staticmethod
    def new_instance(model_type, model_name, model_credential: Dict[str, object], **model_kwargs):
        optional_params = MaxKBBaseModel.filter_optional_params(model_kwargs)
        return OpenAIRerankModel(
            api_key=model_credential.get('api_key'),
            base_url=model_credential.get('api_base'),
            model_name=model_name,
            top_n=optional_params.get('top_n'),
        )

    def rerank(self, query: str, documents: List[str], top_n: int = None) -> List[Dict]:
        """
        重排候选文档
        @param query:      查询语句
        @param documents:  候选文档列表
        @param top_n:      返回数量, 不传则使用模型配置
        @return: [{'index': int, 'relevance_score': float}] 按相关性降序
        """
        if not documents:
            return []
        request_body = {'model': self.model_name, 'query': query, 'documents': documents}
        top_n = top_n if top_n is not None else self.top_n
        if top_n is not None:
            request_body['top_n'] = top_n
        response = requests.post(
            f"{self.base_url}/rerank",
            json=request_body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise Exception(
                f"Rerank request failed with status {response.status_code}: {response.text[:500]}"
            )
        results = response.json().get("results") or []
        result_list = sorted(
            [{"index": item.get("index"), "relevance_score": item.get("relevance_score")} for item in results],
            key=lambda item: item.get("relevance_score") or 0,
            reverse=True,
        )
        return result_list[:top_n] if top_n is not None else result_list
