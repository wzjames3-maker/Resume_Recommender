"""
智能招聘 RAG 推荐系统 - Skill 标准化模块

技能名称标准化、同义词映射、分类
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from src.common.logger import get_logger

logger = get_logger("skill_normalizer")

# 默认模糊匹配阈值
DEFAULT_FUZZY_THRESHOLD = 0.8


class NormalizedSkill(BaseModel):
    """标准化技能"""

    raw_name: str = Field(..., description="原始技能名称")
    normalized_name: str = Field(..., description="标准化后的技能名称")
    category: Optional[str] = Field(None, description="技能分类")
    subcategory: Optional[str] = Field(None, description="技能子分类")
    confidence: float = Field(1.0, description="匹配置信度", ge=0, le=1)
    is_recognized: bool = Field(True, description="是否被识别")


class SkillNormalizationResult(BaseModel):
    """技能标准化结果"""

    normalized_skills: List[NormalizedSkill] = Field(
        default_factory=list, description="标准化后的技能列表"
    )
    unrecognized_skills: List[str] = Field(
        default_factory=list, description="未识别的技能列表"
    )
    total_skills: int = Field(0, description="技能总数")


class SkillNormalizer:
    """技能标准化器"""

    def __init__(self, taxonomy_path: Optional[str] = None):
        """
        初始化技能标准化器

        Args:
            taxonomy_path: 技能分类标准库路径
        """
        self.taxonomy = self._load_taxonomy(taxonomy_path)
        self.skill_index = self._build_skill_index()
        self.fuzzy_threshold = DEFAULT_FUZZY_THRESHOLD

    def _load_taxonomy(self, taxonomy_path: Optional[str]) -> Dict[str, Any]:
        """
        加载技能分类标准库

        Args:
            taxonomy_path: 标准库路径

        Returns:
            Dict: 技能分类标准库
        """
        if taxonomy_path is None:
            # 使用默认路径
            taxonomy_path = str(
                Path(__file__).parent.parent.parent / "data" / "skill_taxonomy.json"
            )

        try:
            with open(taxonomy_path, "r", encoding="utf-8") as f:
                taxonomy = json.load(f)
            logger.info(f"技能分类标准库加载成功: {taxonomy_path}")
            return taxonomy
        except Exception as e:
            logger.warning(f"技能分类标准库加载失败: {str(e)}")
            return {"categories": {}}

    def _build_skill_index(self) -> Dict[str, Tuple[str, str, str]]:
        """
        构建技能索引

        Returns:
            Dict: 技能索引 {别名: (标准化名称, 分类, 子分类)}
        """
        index = {}

        for category_key, category_data in self.taxonomy.get("categories", {}).items():
            category_name = category_data.get("name", category_key)

            for skill_key, skill_data in category_data.get("skills", {}).items():
                normalized_name = skill_data.get("normalized", skill_key)

                # 添加标准化名称
                index[normalized_name.lower()] = (
                    normalized_name,
                    category_name,
                    skill_key,
                )

                # 添加别名
                for alias in skill_data.get("aliases", []):
                    index[alias.lower()] = (
                        normalized_name,
                        category_name,
                        skill_key,
                    )

                # 添加技能键名
                index[skill_key.lower()] = (
                    normalized_name,
                    category_name,
                    skill_key,
                )

        return index

    def normalize(self, skills: List[str]) -> SkillNormalizationResult:
        """
        标准化技能列表

        Args:
            skills: 原始技能列表

        Returns:
            SkillNormalizationResult: 标准化结果
        """
        normalized_skills = []
        unrecognized_skills = []

        for skill in skills:
            if not skill or not skill.strip():
                continue

            skill = skill.strip()

            # 尝试标准化
            normalized = self._normalize_single_skill(skill)

            if normalized.is_recognized:
                normalized_skills.append(normalized)
            else:
                unrecognized_skills.append(skill)
                normalized_skills.append(normalized)

        logger.info(
            f"技能标准化完成: {len(normalized_skills)} 个技能，"
            f"{len(unrecognized_skills)} 个未识别"
        )

        return SkillNormalizationResult(
            normalized_skills=normalized_skills,
            unrecognized_skills=unrecognized_skills,
            total_skills=len(skills),
        )

    def _normalize_single_skill(self, skill: str) -> NormalizedSkill:
        """
        标准化单个技能

        Args:
            skill: 原始技能名称

        Returns:
            NormalizedSkill: 标准化结果
        """
        # 清理技能名称
        cleaned_skill = self._clean_skill_name(skill)

        # 精确匹配
        if cleaned_skill.lower() in self.skill_index:
            normalized_name, category, subcategory = self.skill_index[cleaned_skill.lower()]
            return NormalizedSkill(
                raw_name=skill,
                normalized_name=normalized_name,
                category=category,
                subcategory=subcategory,
                confidence=1.0,
                is_recognized=True,
            )

        # 模糊匹配
        best_match, best_score = self._fuzzy_match(cleaned_skill)

        if best_match and best_score >= self.fuzzy_threshold:
            normalized_name, category, subcategory = best_match
            return NormalizedSkill(
                raw_name=skill,
                normalized_name=normalized_name,
                category=category,
                subcategory=subcategory,
                confidence=best_score,
                is_recognized=True,
            )

        # 未识别
        return NormalizedSkill(
            raw_name=skill,
            normalized_name=skill,
            category="unrecognized",
            subcategory=None,
            confidence=0.0,
            is_recognized=False,
        )

    def _clean_skill_name(self, skill: str) -> str:
        """
        清理技能名称

        Args:
            skill: 原始技能名称

        Returns:
            str: 清理后的技能名称
        """
        # 移除版本号
        skill = re.sub(r"\d+(\.\d+)*", "", skill)

        # 移除括号内容
        skill = re.sub(r"[（(][^）)]*[）)]", "", skill)

        # 移除多余空格
        skill = " ".join(skill.split())

        return skill.strip()

    def _fuzzy_match(
        self, skill: str
    ) -> Tuple[Optional[Tuple[str, str, str]], float]:
        """
        模糊匹配

        Args:
            skill: 技能名称

        Returns:
            Tuple: (最佳匹配, 匹配分数)
        """
        best_match = None
        best_score = 0.0

        skill_lower = skill.lower()

        for indexed_skill, match_data in self.skill_index.items():
            # 计算相似度
            score = SequenceMatcher(None, skill_lower, indexed_skill).ratio()

            if score > best_score:
                best_score = score
                best_match = match_data

        return best_match, best_score

    def add_custom_mapping(
        self, raw_name: str, normalized_name: str, category: str, subcategory: Optional[str] = None
    ) -> None:
        """
        添加自定义映射

        Args:
            raw_name: 原始名称
            normalized_name: 标准化名称
            category: 分类
            subcategory: 子分类
        """
        self.skill_index[raw_name.lower()] = (normalized_name, category, subcategory)
        logger.info(f"添加自定义映射: {raw_name} -> {normalized_name}")

    def set_fuzzy_threshold(self, threshold: float) -> None:
        """
        设置模糊匹配阈值

        Args:
            threshold: 阈值（0-1）
        """
        self.fuzzy_threshold = max(0.0, min(1.0, threshold))
        logger.info(f"设置模糊匹配阈值: {self.fuzzy_threshold}")


# 全局技能标准化器实例
skill_normalizer = SkillNormalizer()


def get_skill_normalizer() -> SkillNormalizer:
    """获取技能标准化器实例"""
    return skill_normalizer
