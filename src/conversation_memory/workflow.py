"""
智能招聘 RAG 推荐系统 - 端到端工作流模块

实现 recruitment.search、recruitment.refine、candidate.lookup 端到端流程
"""

from typing import Any, Dict, List, Optional

from src.common.logger import get_logger
from src.conversation_memory.scope_decider import SearchScope, get_scope_decider
from src.conversation_memory.session_manager import get_session_manager
from src.conversation_memory.slot_merger import MergeStrategy, get_slot_merger
from src.intent_router.schemas import (
    CandidateSlot,
    ConversationContext,
    IntentEnum,
    IntentResult,
    QuerySlot,
)
from src.recommendation_engine.degradation import get_degradation_strategy
from src.recommendation_engine.hybrid_retriever import RetrievalResult, get_hybrid_retriever
from src.recommendation_engine.metadata_filter import get_metadata_filter
from src.recommendation_engine.reason_generator import get_reason_generator
from src.recommendation_engine.reranker import get_reranker
from src.resume_store.repository import get_resume_repository

logger = get_logger("workflow")


class WorkflowResult:
    """工作流结果"""

    def __init__(
        self,
        success: bool,
        message: str,
        candidates: List[Dict[str, Any]],
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.message = message
        self.candidates = candidates
        self.session_id = session_id
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "message": self.message,
            "candidates": self.candidates,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }


class RecruitmentWorkflow:
    """招聘工作流"""

    def __init__(self):
        """初始化工作流"""
        self.session_manager = get_session_manager()
        self.slot_merger = get_slot_merger()
        self.scope_decider = get_scope_decider()
        self.hybrid_retriever = get_hybrid_retriever()
        self.metadata_filter = get_metadata_filter()
        self.reranker = get_reranker()
        self.reason_generator = get_reason_generator()
        self.degradation_strategy = get_degradation_strategy()
        self.resume_repository = get_resume_repository()

    def search(
        self,
        intent_result: IntentResult,
        session_id: Optional[str] = None,
        user_id: str = "default",
    ) -> WorkflowResult:
        """
        执行搜索流程

        Args:
            intent_result: 意图识别结果
            session_id: 会话 ID
            user_id: 用户 ID

        Returns:
            WorkflowResult: 工作流结果
        """
        # 1. 获取或创建会话
        if not session_id:
            session = self.session_manager.create_session(user_id)
            session_id = session.session_id
        else:
            session = self.session_manager.get_session(session_id)
            if not session:
                session = self.session_manager.create_session(user_id)
                session_id = session.session_id

        # 2. 合并 Slots
        context = self.session_manager.get_conversation_context(session_id)
        old_slots = None
        if context and context.get("last_query"):
            old_slots = CandidateSlot(**context["last_query"])

        merged_slots = self.slot_merger.merge_candidate_slots(
            intent_result.candidate_slots,
            old_slots,
            MergeStrategy.INCREMENTAL,
        )

        # 3. 执行混合检索
        try:
            retrieval_results = self.hybrid_retriever.retrieve(merged_slots, raw_query=intent_result.raw_query)
        except Exception as e:
            logger.error(f"混合检索失败: {str(e)}")
            return WorkflowResult(
                success=False,
                message=f"检索失败: {str(e)}",
                candidates=[],
                session_id=session_id,
            )

        # 4. 元数据过滤
        filter_result = self.metadata_filter.filter(retrieval_results, merged_slots)

        # 5. Rerank
        reranked_results = self.reranker.rerank(
            filter_result.results,
            query_text=merged_slots.job_title or intent_result.raw_query
        )
        #         # Enrich results with MongoDB metadata (try UUID id, fallback to ObjectId _id)
        seen_ids = set()
        enriched = []
        for r in reranked_results:
            if r.resume_id in seen_ids:
                continue
            seen_ids.add(r.resume_id)
            try:
                resp = None
                try:
                    resp = self.resume_repository.get(r.resume_id)
                except Exception:
                    from bson import ObjectId
                    from src.resume_store.connection import get_resume_collection
                    col = get_resume_collection()
                    try:
                        doc = col.find_one({"_id": ObjectId(r.resume_id)})
                        if doc:
                            from src.resume_store.models import ResumeSchema
                            resume_obj = ResumeSchema.from_mongodb_dict(doc)
                            resp = self.resume_repository._to_response(resume_obj)
                    except Exception:
                        pass
                if resp:
                    pi = resp.personal_info
                    skills = resp.skill_list or []
                    skill_names = [s.name for s in skills if s.name]
                    r.metadata["candidate_name"] = pi.full_name or ""
                    r.metadata["skills"] = skill_names
                    r.metadata["years_of_experience"] = pi.years_of_experience
                    edu_list = resp.education_list or []
                    highest_edu = ""
                    for edu in edu_list:
                        if edu.degree and (not highest_edu or edu.degree in ["博士","硕士","本科","大专"]):
                            highest_edu = edu.degree
                    r.metadata["highest_education"] = highest_edu
                    r.metadata["expected_city"] = pi.expected_city or ""
                    r.metadata["expected_salary"] = str(pi.expected_salary_range) if pi.expected_salary_range else ""
            except Exception:
                pass
            enriched.append(r)
        reranked_results = enriched

        # Re-dedup by resume_id (different chunks -> same resume)
        seen_ids = set()
        final_deduped = []
        for r in reranked_results:
            if r.resume_id in seen_ids:
                continue
            seen_ids.add(r.resume_id)
            final_deduped.append(r)
        reranked_results = final_deduped

        # 6. 降级策略
        degradation_result = self.degradation_strategy.apply(reranked_results)

        # 7. 生成推荐理由
        candidates = []
        for result in degradation_result.results[:intent_result.query_slots.count]:
            reason = self.reason_generator.generate(result, merged_slots)

            candidates.append({
                "resume_id": result.resume_id,
                "chunk_id": result.chunk_id,
                "content": result.content,
                "score": result.metadata.get("final_score", result.score),
                "rank": result.rank,
                "reason": reason.to_dict(),
                "metadata": result.metadata,
            })

        # 8. 更新会话状态
        self.session_manager.update_session_state(
            session_id,
            last_query=merged_slots.model_dump(),
            last_candidates=candidates,
            last_intent=intent_result.intent.value,
        )

        # 9. 追加消息
        self.session_manager.append_message(
            session_id,
            "user",
            intent_result.raw_query,
        )

        # 构建回复消息
        if candidates:
            message = f"为您找到 {len(candidates)} 位候选人"
            if degradation_result.degradation_reason:
                message += f"（{degradation_result.degradation_reason}）"
        else:
            message = "未找到符合条件的候选人，请尝试放宽搜索条件"

        self.session_manager.append_message(session_id, "assistant", message)

        return WorkflowResult(
            success=True,
            message=message,
            candidates=candidates,
            session_id=session_id,
            metadata={
                "degradation_level": degradation_result.degradation_level,
                "degradation_reason": degradation_result.degradation_reason,
                "filtered_count": filter_result.filtered_count,
                "relaxed_constraints": filter_result.relaxed_constraints,
            },
        )

    def refine(
        self,
        intent_result: IntentResult,
        session_id: str,
    ) -> WorkflowResult:
        """
        执行修正流程

        Args:
            intent_result: 意图识别结果
            session_id: 会话 ID

        Returns:
            WorkflowResult: 工作流结果
        """
        # 检查会话是否存在
        session = self.session_manager.get_session(session_id)
        if not session:
            return WorkflowResult(
                success=False,
                message="会话不存在，请先进行搜索",
                candidates=[],
                session_id=session_id,
            )

        # 获取对话上下文
        context = self.session_manager.get_conversation_context(session_id)

        # 决定检索范围
        scope_decision = self.scope_decider.decide(
            IntentEnum.RECRUITMENT_REFINE,
            intent_result.candidate_slots,
            CandidateSlot(**context["last_query"]) if context.get("last_query") else None,
            context.get("last_candidates"),
        )

        # 合并 Slots
        old_slots = CandidateSlot(**context["last_query"]) if context.get("last_query") else None
        merged_slots = self.slot_merger.merge_candidate_slots(
            intent_result.candidate_slots,
            old_slots,
            MergeStrategy.INCREMENTAL,
        )

        # 根据检索范围执行检索
        if scope_decision.scope == SearchScope.NARROW:
            logger.info("在上次结果中检索")
            candidate_ids = scope_decision.candidate_ids
            if candidate_ids:
                retrieval_results = self.hybrid_retriever.retrieve(merged_slots, raw_query=intent_result.raw_query)
                retrieval_results = [r for r in retrieval_results if r.resume_id in candidate_ids]
                if not retrieval_results:
                    logger.info("NARROW 结果为空，降级为全库检索")
                    retrieval_results = self.hybrid_retriever.retrieve(merged_slots, raw_query=intent_result.raw_query)
            else:
                logger.info("NARROW 无候选ID，降级为全库检索")
                retrieval_results = self.hybrid_retriever.retrieve(merged_slots, raw_query=intent_result.raw_query)
        else:
            logger.info("全库检索")
            retrieval_results = self.hybrid_retriever.retrieve(merged_slots, raw_query=intent_result.raw_query)

        # 后续处理与 search 相同
        filter_result = self.metadata_filter.filter(retrieval_results, merged_slots)
        reranked_results = self.reranker.rerank(filter_result.results, query_text=merged_slots.job_title or intent_result.raw_query)
        degradation_result = self.degradation_strategy.apply(reranked_results)

        candidates = []
        for result in degradation_result.results[:intent_result.query_slots.count]:
            reason = self.reason_generator.generate(result, merged_slots)

            candidates.append({
                "resume_id": result.resume_id,
                "chunk_id": result.chunk_id,
                "content": result.content,
                "score": result.metadata.get("final_score", result.score),
                "rank": result.rank,
                "reason": reason.to_dict(),
                "metadata": result.metadata,
            })

        # 更新会话状态
        self.session_manager.update_session_state(
            session_id,
            last_query=merged_slots.model_dump(),
            last_candidates=candidates,
            last_intent=intent_result.intent.value,
        )

        # 追加消息
        self.session_manager.append_message(
            session_id,
            "user",
            intent_result.raw_query,
        )

        if candidates:
            message = f"为您找到 {len(candidates)} 位候选人"
        else:
            message = "未找到符合条件的候选人，请尝试放宽搜索条件"

        self.session_manager.append_message(session_id, "assistant", message)

        return WorkflowResult(
            success=True,
            message=message,
            candidates=candidates,
            session_id=session_id,
            metadata={
                "scope": scope_decision.scope.value,
                "scope_reason": scope_decision.reason,
            },
        )

    def lookup(
        self,
        intent_result: IntentResult,
        session_id: Optional[str] = None,
    ) -> WorkflowResult:
        """
        执行查看候选人详情流程

        Args:
            intent_result: 意图识别结果
            session_id: 会话 ID

        Returns:
            WorkflowResult: 工作流结果
        """
        # 从 Slots 中提取候选人标识
        slots = intent_result.candidate_slots

        # 尝试从上次结果中查找
        if session_id:
            session = self.session_manager.get_session(session_id)
            if session and session.last_candidates:
                # 在上次结果中查找
                for candidate in session.last_candidates:
                    # 简单匹配（实际应该更智能）
                    if slots.job_title and slots.job_title in candidate.get("content", ""):
                        return WorkflowResult(
                            success=True,
                            message="找到候选人详情",
                            candidates=[candidate],
                            session_id=session_id,
                        )

        # 如果没有找到，返回提示
        return WorkflowResult(
            success=True,
            message="请先进行搜索，然后查看候选人详情",
            candidates=[],
            session_id=session_id,
        )


# 全局工作流实例
recruitment_workflow = RecruitmentWorkflow()


def get_recruitment_workflow() -> RecruitmentWorkflow:
    """获取工作流实例"""
    return recruitment_workflow
