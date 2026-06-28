"""
智能招聘 RAG 推荐系统 - 意图路由测试
"""

import pytest

from src.intent_router.router import (
    HandlerResponse,
    IntentRouter,
    get_intent_router,
)

# Note: Handler classes (SearchHandler/RefineHandler/LookupHandler/ChatHandler/FallbackHandler)
# removed in v1.2-data-pipeline. Routing now via chat.py mapping table.

from src.intent_router.schemas import (
    CandidateSlot,
    ConversationContext,
    IntentEnum,
    IntentResult,
    QuerySlot,
)


@pytest.fixture
def router():
    """创建路由分发器实例"""
    return IntentRouter()


@pytest.fixture
def sample_intent_result():
    """示例意图识别结果"""
    return IntentResult(
        intent=IntentEnum.RECRUITMENT_SEARCH,
        confidence=0.9,
        candidate_slots=CandidateSlot(job_title="Java工程师"),
        query_slots=QuerySlot(),
        raw_query="帮我找Java工程师",
    )


class TestHandlerResponse:
    """HandlerResponse 测试"""

    def test_create_success_response(self):
        """测试创建成功响应"""
        response = HandlerResponse(
            success=True,
            message="处理成功",
            data={"key": "value"},
        )

        assert response.success is True
        assert response.message == "处理成功"
        assert response.data == {"key": "value"}
        assert response.error is None

    def test_create_error_response(self):
        """测试创建错误响应"""
        response = HandlerResponse(
            success=False,
            message="处理失败",
            error="Something went wrong",
        )

        assert response.success is False
        assert response.error == "Something went wrong"

    def test_to_dict(self):
        """测试转换为字典"""
        response = HandlerResponse(
            success=True,
            message="处理成功",
            data={"key": "value"},
        )

        data = response.to_dict()

        assert data["success"] is True
        assert data["message"] == "处理成功"
        assert data["data"] == {"key": "value"}


class TestHandlers:
    """Handler 测试"""

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline; routing now in chat.py")
    @pytest.mark.asyncio
    async def test_search_handler(self):
        ...

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    @pytest.mark.asyncio
    async def test_refine_handler(self):
        ...

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    @pytest.mark.asyncio
    async def test_lookup_handler(self):
        ...

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    @pytest.mark.asyncio
    async def test_chat_handler(self):
        ...

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    @pytest.mark.asyncio
    async def test_fallback_handler(self):
        ...


class TestIntentRouter:
    """IntentRouter 测试"""

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    def test_register_handler(self, router):
        ...

    def test_unregister_handler(self, router):
        """测试注销处理器"""
        router.unregister(IntentEnum.RECRUITMENT_SEARCH)
        assert router.get_handler(IntentEnum.RECRUITMENT_SEARCH) is None

    def test_get_registered_intents(self, router):
        """测试获取已注册意图"""
        intents = router.get_registered_intents()
        assert isinstance(intents, list)

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    @pytest.mark.asyncio
    async def test_route_to_search(self, router, sample_intent_result):
        ...

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    @pytest.mark.asyncio
    async def test_route_to_chat(self, router):
        ...

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    @pytest.mark.asyncio
    async def test_route_to_fallback(self, router):
        ...

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    @pytest.mark.asyncio
    async def test_route_with_context(self, router, sample_intent_result):
        ...

    @pytest.mark.skip(reason="Handler classes removed in v1.2-data-pipeline")
    @pytest.mark.asyncio
    async def test_route_unknown_intent(self, router):
        ...

    def test_get_intent_router(self):
        """测试获取全局实例"""
        router = get_intent_router()
        assert isinstance(router, IntentRouter)
