"""
智能招聘 RAG 推荐系统 - 解析失败降级处理模块

三级降级策略：完整解析 → 部分解析 → 原文存储
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.common.errors import ErrorCode, ValidationError
from src.common.logger import get_logger
from src.resume_parser.llm_extractor import ExtractionWarning, ResumeStructured
from src.resume_store.models import (
    EducationEntry,
    ExperienceEntry,
    PersonalInfo,
    ParseStatus,
    ProjectEntry,
    SkillEntry,
)

logger = get_logger("fallback_handler")


class FallbackLevel(str, Enum):
    """降级级别"""

    FULL = "full"  # 完整解析
    PARTIAL = "partial"  # 部分解析
    RAW = "raw"  # 原文存储


class FallbackResult(BaseModel):
    """降级结果"""

    level: FallbackLevel = Field(..., description="降级级别")
    parse_status: ParseStatus = Field(..., description="解析状态")
    structured: Optional[ResumeStructured] = Field(None, description="结构化数据")
    raw_text: Optional[str] = Field(None, description="原始文本")
    extraction_warnings: List[ExtractionWarning] = Field(
        default_factory=list, description="提取警告"
    )
    fallback_reason: Optional[str] = Field(None, description="降级原因")


class FallbackHandler:
    """降级处理器"""

    # 关键字段缺失率阈值
    MISSING_RATE_THRESHOLD = 0.7

    # 关键字段列表
    CRITICAL_FIELDS = [
        "personal_info.full_name",
        "personal_info.phone",
        "personal_info.email",
        "education_list",
        "experience_list",
        "skill_list",
    ]

    def handle(
        self,
        text: str,
        structured: Optional[ResumeStructured] = None,
        error: Optional[Exception] = None,
    ) -> FallbackResult:
        """
        处理解析结果，执行降级策略

        Args:
            text: 原始文本
            structured: 结构化数据（可能为 None）
            error: 异常信息（可能为 None）

        Returns:
            FallbackResult: 降级结果
        """
        # 检查是否需要降级
        need_fallback, reason = self._check_fallback_needed(structured, error)

        if not need_fallback and structured:
            # 完整解析成功
            return FallbackResult(
                level=FallbackLevel.FULL,
                parse_status=ParseStatus.SUCCESS,
                structured=structured,
                extraction_warnings=structured.extraction_warnings,
            )

        # 尝试部分解析
        if structured:
            partial_result = self._try_partial_parse(structured)
            if partial_result:
                logger.info(f"进入部分解析模式: {reason}")
                return FallbackResult(
                    level=FallbackLevel.PARTIAL,
                    parse_status=ParseStatus.PARTIAL,
                    structured=partial_result,
                    extraction_warnings=partial_result.extraction_warnings,
                    fallback_reason=reason,
                )

        # 降级到原文存储
        logger.warning(f"降级到原文存储模式: {reason}")
        return FallbackResult(
            level=FallbackLevel.RAW,
            parse_status=ParseStatus.FAILED if error else ParseStatus.PARTIAL,
            raw_text=text,
            extraction_warnings=[
                ExtractionWarning(
                    field="all",
                    message=f"解析失败，降级为原文存储: {reason}",
                    confidence=0.0,
                )
            ],
            fallback_reason=reason,
        )

    def _check_fallback_needed(
        self,
        structured: Optional[ResumeStructured],
        error: Optional[Exception],
    ) -> tuple[bool, Optional[str]]:
        """
        检查是否需要降级

        Args:
            structured: 结构化数据
            error: 异常信息

        Returns:
            tuple: (是否需要降级, 原因)
        """
        # 有异常，需要降级
        if error:
            return True, f"解析异常: {str(error)}"

        # 没有结构化数据，需要降级
        if not structured:
            return True, "未返回结构化数据"

        # 检查关键字段缺失率
        missing_rate = self._calculate_missing_rate(structured)
        if missing_rate > self.MISSING_RATE_THRESHOLD:
            return True, f"关键字段缺失率过高: {missing_rate:.1%}"

        # 检查置信度
        if structured.confidence_score < 0.3:
            return True, f"置信度过低: {structured.confidence_score}"

        return False, None

    def _calculate_missing_rate(self, structured: ResumeStructured) -> float:
        """
        计算关键字段缺失率

        Args:
            structured: 结构化数据

        Returns:
            float: 缺失率（0-1）
        """
        missing_count = 0
        total_count = len(self.CRITICAL_FIELDS)

        # 检查个人信息
        if not structured.personal_info.full_name:
            missing_count += 1
        if not structured.personal_info.phone:
            missing_count += 1
        if not structured.personal_info.email:
            missing_count += 1

        # 检查列表字段
        if not structured.education_list:
            missing_count += 1
        if not structured.experience_list:
            missing_count += 1
        if not structured.skill_list:
            missing_count += 1

        return missing_count / total_count

    def _try_partial_parse(
        self, structured: ResumeStructured
    ) -> Optional[ResumeStructured]:
        """
        尝试部分解析

        Args:
            structured: 结构化数据

        Returns:
            Optional[ResumeStructured]: 部分解析结果，如果完全无法解析返回 None
        """
        # 检查是否有任何有效数据
        has_any_data = (
            structured.personal_info.full_name
            or structured.education_list
            or structured.experience_list
            or structured.skill_list
        )

        if not has_any_data:
            return None

        # 添加缺失字段警告
        warnings = list(structured.extraction_warnings)

        if not structured.personal_info.full_name:
            warnings.append(ExtractionWarning(
                field="personal_info.full_name",
                message="姓名提取失败",
                confidence=0.0,
            ))

        if not structured.personal_info.phone:
            warnings.append(ExtractionWarning(
                field="personal_info.phone",
                message="手机号提取失败",
                confidence=0.0,
            ))

        if not structured.personal_info.email:
            warnings.append(ExtractionWarning(
                field="personal_info.email",
                message="邮箱提取失败",
                confidence=0.0,
            ))

        if not structured.education_list:
            warnings.append(ExtractionWarning(
                field="education_list",
                message="教育经历提取失败",
                confidence=0.0,
            ))

        if not structured.experience_list:
            warnings.append(ExtractionWarning(
                field="experience_list",
                message="工作经历提取失败",
                confidence=0.0,
            ))

        if not structured.skill_list:
            warnings.append(ExtractionWarning(
                field="skill_list",
                message="技能列表提取失败",
                confidence=0.0,
            ))

        return ResumeStructured(
            personal_info=structured.personal_info,
            education_list=structured.education_list,
            experience_list=structured.experience_list,
            project_list=structured.project_list,
            skill_list=structured.skill_list,
            extraction_warnings=warnings,
            confidence_score=structured.confidence_score,
        )


# 全局降级处理器实例
fallback_handler = FallbackHandler()


def get_fallback_handler() -> FallbackHandler:
    """获取降级处理器实例"""
    return fallback_handler
