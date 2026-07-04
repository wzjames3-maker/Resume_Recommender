"""
智能招聘 RAG 推荐系统 - LangGraph Agent

变更 (Tier L): 使用 LangGraph StateGraph 替代 if/elif 硬编码路由
"""

from typing import Any, Dict, List, Optional, TypedDict

from src.common.logger import get_logger
from src.intent_router.schemas import (
    CandidateSlot,
    ConversationContext,
    IntentEnum,
    IntentResult,
)

logger = get_logger(__name__)


class AgentState(TypedDict, total=False):
    """LangGraph Agent 状态"""
    messages: List[Dict[str, Any]]
    intent: Optional[str]
    confidence: float
    slots: Optional[Dict[str, Any]]
    raw_query: str
    conversation_id: Optional[str]
    retrieval_results: List[Dict[str, Any]]
    candidates: List[Dict[str, Any]]
    degradation: Optional[Dict[str, Any]]
    error: Optional[str]
    response: Optional[Dict[str, Any]]
    # 字段用于 LangGraph interrupt/resume
    __interrupt__: Optional[Dict[str, Any]]


class IntentRouterAgent:
    """LangGraph Intent Router Agent"""

    def __init__(self):
        self._compiled = None

    def build_graph(self):
        """构建 LangGraph StateGraph（懒加载）"""
        if self._compiled is not None:
            return self._compiled

        from langgraph.graph import StateGraph, END

        workflow = StateGraph(AgentState)

        workflow.add_node("intent_classifier", self._classify_intent)
        workflow.add_node("slot_extractor", self._extract_slots)
        workflow.add_node("hybrid_search", self._hybrid_search)
        workflow.add_node("rerank", self._rerank)
        workflow.add_node("build_context", self._build_context)
        workflow.add_node("generate_reasons", self._generate_reasons)
        workflow.add_node("fallback", self._fallback)

        workflow.set_entry_point("intent_classifier")

        workflow.add_conditional_edges(
            "intent_classifier",
            self._route_intent,
            {
                "search": "slot_extractor",
                "refine": "slot_extractor",
                "fallback": "fallback",
            },
        )

        workflow.add_edge("slot_extractor", "hybrid_search")
        workflow.add_edge("hybrid_search", "rerank")
        workflow.add_edge("rerank", "build_context")
        workflow.add_edge("build_context", "generate_reasons")
        workflow.add_edge("generate_reasons", END)
        workflow.add_edge("fallback", END)

        self._compiled = workflow.compile()
        logger.info("LangGraph StateGraph 构建完成")
        return self._compiled

    def run(self, query: str, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """执行 Agent"""
        graph = self.build_graph()
        initial_state: AgentState = {
            "messages": [{"role": "user", "content": query}],
            "raw_query": query,
            "conversation_id": conversation_id,
            "intent": None,
            "confidence": 0.0,
            "slots": None,
            "retrieval_results": [],
            "candidates": [],
        }
        result = graph.invoke(initial_state)
        return result

    # ── LangGraph Nodes ──

    def _classify_intent(self, state: AgentState) -> AgentState:
        """Intent 分类节点"""
        from src.intent_router.classifier import get_intent_classifier

        classifier = get_intent_classifier()
        query = state.get("raw_query", "")
        conversation_id = state.get("conversation_id")

        result = classifier.classify(query, conversation_id)

        state["intent"] = result.intent.value if result.intent else "fallback"
        state["confidence"] = result.confidence
        state["slots"] = self._slots_to_dict(result.candidate_slots)
        logger.info(f"Intent: {state['intent']}, confidence: {state['confidence']}")
        return state

    def _extract_slots(self, state: AgentState) -> AgentState:
        """Slot 提取节点（合并 conversation context）"""
        logger.info(f"Slots: {state.get('slots')}")
        return state

    def _hybrid_search(self, state: AgentState) -> AgentState:
        """Hybrid Search 节点"""
        from src.recommendation_engine.hybrid_retriever import get_hybrid_retriever
        from src.intent_router.schemas import CandidateSlot

        slots = CandidateSlot(**state.get("slots", {}))
        retriever = get_hybrid_retriever()
        results = retriever.retrieve(slots=slots, raw_query=state.get("raw_query", ""))
        state["retrieval_results"] = [r.to_dict() for r in results]
        logger.info(f"检索结果: {len(results)} 个候选人")
        return state

    def _rerank(self, state: AgentState) -> AgentState:
        """Rerank 节点"""
        from src.recommendation_engine.hybrid_retriever import RetrievalResult
        from src.recommendation_engine.reranker import get_reranker

        raw = state.get("retrieval_results", [])
        results = [RetrievalResult(**r) for r in raw]

        query_text = self._build_rerank_query(state)
        reranker = get_reranker()
        ranked = reranker.rerank(results, query_text=query_text)
        state["retrieval_results"] = [r.to_dict() for r in ranked]
        return state

    def _build_context(self, state: AgentState) -> AgentState:
        """构建 LLM 上下文"""
        state["candidates"] = state.get("retrieval_results", [])
        return state

    def _generate_reasons(self, state: AgentState) -> AgentState:
        """LLM 推荐理由生成"""
        from src.intent_router.schemas import CandidateSlot
        from src.recommendation_engine.hybrid_retriever import RetrievalResult
        from src.recommendation_engine.reason_generator import get_reason_generator

        slots = CandidateSlot(**state.get("slots", {}))
        generator = get_reason_generator()
        candidates = state.get("candidates", [])

        results = []
        for c in candidates[:10]:
            result = RetrievalResult(**c)
            reason = generator.generate(result, slots)
            results.append({"candidate": c, "reason": reason.to_dict()})

        state["response"] = {
            "intent": state.get("intent"),
            "candidates": results,
            "total": len(results),
        }
        return state

    def _fallback(self, state: AgentState) -> AgentState:
        """Fallback 节点"""
        state["response"] = {
            "intent": "fallback",
            "message": "请输入招聘需求，例如：「帮我找5年经验的Java工程师，本科以上，在杭州」",
        }
        return state

    def _route_intent(self, state: AgentState) -> str:
        """条件路由：根据 intent 决定下一个节点"""
        intent = state.get("intent", "fallback")
        confidence = state.get("confidence", 0.0)

        if confidence < 0.6:
            return "fallback"

        if intent in ("recruitment.search", "recruitment.refine"):
            return "search"
        return "fallback"

    def _build_rerank_query(self, state: AgentState) -> str:
        slots = state.get("slots", {})
        parts = ["招聘需求："]
        job_title = slots.get("job_title")
        skills = slots.get("skills", [])
        experience = slots.get("experience")
        education = slots.get("education")
        city = slots.get("city")

        if job_title:
            parts.append(f"岗位: {job_title}")
        if experience is not None:
            parts.append(f"经验: {int(experience)}年以上")
        if education:
            parts.append(f"学历: {education}及以上")
        if city:
            parts.append(f"城市: {city}")
        if skills:
            parts.append(f"技能: {', '.join(skills)}")
        return " ".join(parts)

    def _slots_to_dict(self, slots: Any) -> Dict[str, Any]:
        if slots is None:
            return {}
        if isinstance(slots, dict):
            return slots
        if hasattr(slots, "model_dump"):
            return slots.model_dump()
        if hasattr(slots, "dict"):
            return slots.dict()
        return {}


_agent: Optional[IntentRouterAgent] = None


def get_agent() -> IntentRouterAgent:
    global _agent
    if _agent is None:
        _agent = IntentRouterAgent()
    return _agent
