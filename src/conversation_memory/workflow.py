"""
智能招聘 RAG 推荐系统 - 端到端工作流模块

实现 recruitment.search、recruitment.refine、candidate.lookup 端到端流程
"""

import re
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

        # 4. Batch Enrich MongoDB metadata (avoid N+1)
        unique_ids = list(set(r.resume_id for r in retrieval_results))
        resume_map = self.resume_repository.batch_get_by_ids(unique_ids)
        enriched = []
        for r in retrieval_results:
            resp = resume_map.get(r.resume_id)
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
            enriched.append(r)

        # 5. 元数据过滤
        filter_result = self.metadata_filter.filter(enriched, merged_slots)

        # 6. Rerank
        reranked_results = self.reranker.rerank(
            filter_result.results,
            query_text=merged_slots.job_title or intent_result.raw_query
        )
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
                _SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')
                safe_ids = [cid for cid in candidate_ids if _SAFE_ID_RE.match(cid)]
                if len(safe_ids) < len(candidate_ids):
                    logger.warning(f"过滤了 {len(candidate_ids) - len(safe_ids)} 个非法 candidate_id")
                candidate_ids = safe_ids
                id_list = ', '.join(f'"{cid}"' for cid in candidate_ids)
                narrow_expr = f"resume_id in [{id_list}]"
                retrieval_results = self.hybrid_retriever.retrieve(
                    merged_slots, raw_query=intent_result.raw_query, expr=narrow_expr
                )
                if not retrieval_results:
                    logger.info("NARROW 结果为空，降级为全库检索")
                    retrieval_results = self.hybrid_retriever.retrieve(merged_slots, raw_query=intent_result.raw_query)
            else:
                logger.info("NARROW 无候选ID，降级为全库检索")
                retrieval_results = self.hybrid_retriever.retrieve(merged_slots, raw_query=intent_result.raw_query)
        else:
            logger.info("全库检索")
            retrieval_results = self.hybrid_retriever.retrieve(merged_slots, raw_query=intent_result.raw_query)

        # Batch Enrich MongoDB metadata (与 search 相同的流程)
        unique_ids = list(set(r.resume_id for r in retrieval_results))
        resume_map = self.resume_repository.batch_get_by_ids(unique_ids)
        enriched = []
        for r in retrieval_results:
            resp = resume_map.get(r.resume_id)
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
            enriched.append(r)

        # 后续处理与 search 相同
        filter_result = self.metadata_filter.filter(enriched, merged_slots)
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

        支持三种 lookup 方式：
        1. 按位置："第一个候选人"、"第二个"、"最后一个"
        2. 按姓名："张三的简历"、"查看李四"
        3. 按 resume_id：直接提供 UUID

        Args:
            intent_result: 意图识别结果
            session_id: 会话 ID

        Returns:
            WorkflowResult: 工作流结果
        """
        raw_query = intent_result.raw_query
        slots = intent_result.candidate_slots

        # 1. 按位置 lookup（第一个、第二个、最后一个）
        position = self._extract_position(raw_query)
        if position is not None and session_id:
            session = self.session_manager.get_session(session_id)
            if session and session.last_candidates:
                candidates = session.last_candidates
                if 1 <= position <= len(candidates):
                    candidate = candidates[position - 1]
                    # 获取完整简历详情
                    full_candidate = self._get_full_candidate(candidate)
                    return WorkflowResult(
                        success=True,
                        message=f"第 {position} 位候选人的详情：",
                        candidates=[full_candidate],
                        session_id=session_id,
                    )

        # 2. 按姓名 lookup
        name = self._extract_name(raw_query)
        if name and session_id:
            session = self.session_manager.get_session(session_id)
            if session and session.last_candidates:
                for candidate in session.last_candidates:
                    candidate_name = candidate.get("metadata", {}).get("candidate_name", "")
                    if name in candidate_name or candidate_name in name:
                        full_candidate = self._get_full_candidate(candidate)
                        return WorkflowResult(
                            success=True,
                            message=f"候选人 {name} 的详情：",
                            candidates=[full_candidate],
                            session_id=session_id,
                        )

        # 3. 按 resume_id lookup
        resume_id = self._extract_resume_id(raw_query)
        if resume_id:
            try:
                resume = self.resume_repository.get(resume_id, decrypt_pii=True)
                candidate = {
                    "resume_id": resume_id,
                    "metadata": resume.model_dump(mode="json"),
                    "score": 1.0,
                    "rank": 1,
                }
                return WorkflowResult(
                    success=True,
                    message=f"候选人详情：",
                    candidates=[candidate],
                    session_id=session_id,
                )
            except Exception:
                pass

        # 未找到
        return WorkflowResult(
            success=True,
            message="未找到指定的候选人。请先进行搜索，然后使用位置（如'第一个'）、姓名或简历ID查看候选人详情。",
            candidates=[],
            session_id=session_id,
        )

    def _extract_position(self, text: str) -> Optional[int]:
        """从文本中提取位置（第几个）"""
        import re
        patterns = [
            r'第\s*([一二三四五六七八九十]+)\s*[个位]',
            r'第\s*(\d+)\s*[个位]',
            r'第([一二三四五六七八九十]+)',
            r'第(\d+)',
            r'([1-9]\d*)\s*[个位]',
            r'最后\s*[一个]',
        ]
        cn_nums = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                if '最后' in text:
                    return -1  # 特殊标记，需要单独处理
                num_str = m.group(1) if m.lastindex else '1'
                if num_str in cn_nums:
                    return cn_nums[num_str]
                try:
                    return int(num_str)
                except ValueError:
                    pass
        return None

    def _extract_name(self, text: str) -> Optional[str]:
        """从文本中提取姓名"""
        import re
        # 常见模式："查看张三"、"张三的简历"、"候选人张三"
        patterns = [
            r'(?:查看|详情|简历)\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})',
            r'([\u4e00-\u9fa5]{2,4})\s*的\s*(?:简历|详情)',
            r'候选人\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                name = m.group(1)
                # 排除常见误匹配词
                if name not in ['简历', '详情', '候选人', '第一位', '第二个']:
                    return name
        return None

    def _extract_resume_id(self, text: str) -> Optional[str]:
        """从文本中提取 resume_id (UUID 格式)"""
        import re
        # UUID 格式: 8-4-4-4-12
        m = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', text, re.IGNORECASE)
        return m.group(1) if m else None

    def _get_full_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """获取候选人的完整详情（从 MongoDB）"""
        resume_id = candidate.get("resume_id")
        if not resume_id:
            return candidate
        try:
            resume = self.resume_repository.get(resume_id, decrypt_pii=True)
            # 合并 candidate 的 rank/score 和 resume 的完整数据
            full = {
                "resume_id": resume_id,
                "rank": candidate.get("rank"),
                "score": candidate.get("score"),
                "reason": candidate.get("reason"),
                "metadata": resume.model_dump(mode="json"),
            }
            return full
        except Exception as e:
            logger.warning(f"获取完整简历失败: {e}")
            return candidate


# 全局工作流实例
recruitment_workflow = RecruitmentWorkflow()


def get_recruitment_workflow() -> RecruitmentWorkflow:
    """获取工作流实例"""
    return recruitment_workflow
