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

    @pytest.mark.asyncio
    async def test_search_handler(self):
        """测试搜索处理器"""
        handler = SearchHandler()
        intent_result = IntentResult(
            intent=IntentEnum.RECRUITMENT_SEARCH,
            confidence=0.9,
            candidate_slots=CandidateSlot(job_title="Java工程师"),
            query_slots=QuerySlot(),
            raw_query="帮我找Java工程师",
        )

        response = await handler.handle(intent_result)

        assert response.success is True
        assert "intent" in response.data

    @pytest.mark.asyncio
    async def test_refine_handler(self):
        """测试修正处理器"""
        handler = RefineHandler()
        intent_result = IntentResult(
            intent=IntentEnum.RECRUITMENT_REFINE,
            confidence=0.9,
            candidate_slots=CandidateSlot(),
            query_slots=QuerySlot(sort_by="experience"),
            raw_query="按经验排序",
        )

        response = await handler.handle(intent_result)

        assert response.success is True

    @pytest.mark.asyncio
    async def test_lookup_handler(self):
        """测试查看处理器"""
        handler = LookupHandler()
        intent_result = IntentResult(
            intent=IntentEnum.CANDIDATE_LOOKUP,
            confidence=0.9,
            candidate_slots=CandidateSlot(job_title="张三"),
            query_slots=QuerySlot(),
            raw_query="张三的简历",
        )

        response = await handler.handle(intent_result)

        assert response.success is True

    @pytest.mark.asyncio
    async def test_chat_handler(self):
        """测试闲聊处理器"""
        handler = ChatHandler()
        intent_result = IntentResult(
            intent=IntentEnum.CHAT,
            confidence=0.9,
            candidate_slots=CandidateSlot(),
            query_slots=QuerySlot(),
            raw_query="你好",
        )

        response = await handler.handle(intent_result)

        assert response.success is True
        assert "你好" in response.message

    @pytest.mark.asyncio
    async def test_fallback_handler(self):
        """测试兜底处理器"""
        handler = FallbackHandler()
        intent_result = IntentResult(
            intent=IntentEnum.FALLBACK,
            confidence=0.5,
            candidate_slots=CandidateSlot(),
            query_slots=QuerySlot(),
            raw_query="一些无法识别的输入",
        )

        response = await handler.handle(intent_result)

        assert response.success is True
        assert "抱歉" in response.message


class TestIntentRouter:
    """IntentRouter 测试"""

    def test_register_handler(self, router):
        """测试注册处理器"""
        handler = SearchHandler()
        router.register(IntentEnum.RECRUITMENT_SEARCH, handler)

        assert router.get_handler(IntentEnum.RECRUITMENT_SEARCH) is handler

    def test_unregister_handler(self, router):
        """测试注销处理器"""
        router.unregister(IntentEnum.RECRUITMENT_SEARCH)

        assert router.get_handler(IntentEnum.RECRUITMENT_SEARCH) is None

    def test_get_registered_intents(self, router):
        """测试获取已注册意图"""
        intents = router.get_registered_intents()

        assert IntentEnum.RECRUITMENT_SEARCH in intents
        assert IntentEnum.CHAT in intents
        assert IntentEnum.FALLBACK in intents

    @pytest.mark.asyncio
    async def test_route_to_search(self, router, sample_intent_result):
        """测试路由到搜索"""
        response = await router.route(sample_intent_result)

        assert response.success is True
        assert response.data.get("intent") == IntentEnum.RECRUITMENT_SEARCH.value

    @pytest.mark.asyncio
    async def test_route_to_chat(self, router):
        """测试路由到闲聊"""
        intent_result = IntentResult(
            intent=IntentEnum.CHAT,
            confidence=0.9,
            candidate_slots=CandidateSlot(),
            query_slots=QuerySlot(),
            raw_query="你好",
        )

        response = await router.route(intent_result)

        assert response.success is True
        assert "你好" in response.message

    @pytest.mark.asyncio
    async def test_route_to_fallback(self, router):
        """测试路由到兜底"""
        intent_result = IntentResult(
            intent=IntentEnum.FALLBACK,
            confidence=0.5,
            candidate_slots=CandidateSlot(),
            query_slots=QuerySlot(),
            raw_query="一些无法识别的输入",
        )

        response = await router.route(intent_result)

        assert response.success is True
        assert "抱歉" in response.message

    @pytest.mark.asyncio
    async def test_route_with_context(self, router, sample_intent_result):
        """测试带上下文的路由"""
        context = ConversationContext(
            conversation_id="conv-001",
            turn_count=1,
        )

        response = await router.route(sample_intent_result, context)

        assert response.success is True

    @pytest.mark.asyncio
    async def test_route_unknown_intent(self, router):
        """测试路由未知意图（应该使用兜底处理器）"""
        # 创建一个未注册的意图
        intent_result = IntentResult(
            intent=IntentEnum.KNOWLEDGE_QA,
            confidence=0.5,
            candidate_slots=CandidateSlot(),
            query_slots=QuerySlot(),
            raw_query="知识问答",
        )

        response = await router.route(intent_result)

        assert response.success is True

    def test_get_intent_router(self):
        """测试获取全局实例"""
        router = get_intent_router()
        assert isinstance(router, IntentRouter)
