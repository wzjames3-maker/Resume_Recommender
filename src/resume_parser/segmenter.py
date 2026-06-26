"""
智能招聘 RAG 推荐系统 - 语义段落切分模块

将简历文本切分为语义段落（Segment）
"""

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from src.common.logger import get_logger

logger = get_logger("segmenter")


class SectionType(str, Enum):
    """段落类型"""

    PERSONAL_INFO = "personal_info"  # 个人信息
    EDUCATION = "education"  # 教育经历
    EXPERIENCE = "experience"  # 工作经历
    PROJECT = "project"  # 项目经历
    SKILL = "skill"  # 技能
    CERTIFICATE = "certificate"  # 证书
    OTHER = "other"  # 其他


class Segment(BaseModel):
    """语义段落"""

    segment_type: SectionType = Field(..., description="段落类型")
    content: str = Field(..., description="段落内容")
    title: Optional[str] = Field(None, description="段落标题")
    organization: Optional[str] = Field(None, description="组织机构（学校/公司）")
    start_date: Optional[str] = Field(None, description="开始日期")
    end_date: Optional[str] = Field(None, description="结束日期")
    position: Optional[int] = Field(None, description="在原文中的位置")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class OverlapWarning(BaseModel):
    """重叠警告"""

    segment1_index: int = Field(..., description="段落1索引")
    segment2_index: int = Field(..., description="段落2索引")
    overlap_type: str = Field(..., description="重叠类型")
    message: str = Field(..., description="警告信息")


class SegmentationResult(BaseModel):
    """切分结果"""

    segments: List[Segment] = Field(default_factory=list, description="段落列表")
    warnings: List[OverlapWarning] = Field(default_factory=list, description="重叠警告")
    total_segments: int = Field(0, description="段落总数")


class Segmenter:
    """语义段落切分器"""

    # 段落类型关键词
    SECTION_KEYWORDS = {
        SectionType.EDUCATION: [
            "教育经历", "教育背景", "学历", "教育", "学习经历",
            "education", "academic", "学历信息",
        ],
        SectionType.EXPERIENCE: [
            "工作经历", "工作经验", "工作", "职业经历", "实习经历",
            "experience", "employment", "work history", "实习",
        ],
        SectionType.PROJECT: [
            "项目经历", "项目经验", "项目", "项目描述",
            "project", "projects", "项目经验",
        ],
        SectionType.SKILL: [
            "技能", "专业技能", "技术栈", "技能特长", "个人技能",
            "skills", "technical skills", "技术能力", "专业能力",
        ],
        SectionType.CERTIFICATE: [
            "证书", "资质", "认证", "获奖", "荣誉",
            "certificates", "certifications", "awards",
        ],
    }

    # 日期正则表达式
    DATE_PATTERNS = [
        r"(\d{4})\s*[-.年]\s*(\d{1,2})\s*[-.月]?\s*(?:[-至到]\s*(?:(\d{4})\s*[-.年]\s*(\d{1,2})\s*[-.月]?|至今|现在))?",
        r"(\d{4})\s*[-.年]\s*(?:[-至到]\s*(?:(\d{4})\s*[-.年]?|至今|现在))?",
    ]

    def segment(self, text: str) -> SegmentationResult:
        """
        将简历文本切分为语义段落

        Args:
            text: 简历原始文本

        Returns:
            SegmentationResult: 切分结果
        """
        if not text or not text.strip():
            return SegmentationResult(segments=[], warnings=[], total_segments=0)

        # 分割文本为行
        lines = text.split("\n")

        # 识别段落边界
        section_boundaries = self._identify_section_boundaries(lines)

        # 提取段落
        segments = self._extract_segments(lines, section_boundaries)

        # 检测重叠
        warnings = self._detect_overlaps(segments)

        logger.info(f"段落切分完成，共 {len(segments)} 个段落，{len(warnings)} 个重叠警告")

        return SegmentationResult(
            segments=segments,
            warnings=warnings,
            total_segments=len(segments),
        )

    def _identify_section_boundaries(
        self, lines: List[str]
    ) -> List[Tuple[int, SectionType, str]]:
        """
        识别段落边界

        Args:
            lines: 文本行列表

        Returns:
            List[Tuple[int, SectionType, str]]: (行号, 段落类型, 标题) 列表
        """
        boundaries = []

        for i, line in enumerate(lines):
            line_lower = line.strip().lower()

            # 跳过空行
            if not line_lower:
                continue

            # 检查是否为段落标题
            for section_type, keywords in self.SECTION_KEYWORDS.items():
                matched = False
                for keyword in keywords:
                    if keyword in line_lower:
                        boundaries.append((i, section_type, line.strip()))
                        matched = True
                        break
                if matched:
                    break

        return boundaries

    def _extract_segments(
        self,
        lines: List[str],
        boundaries: List[Tuple[int, SectionType, str]],
    ) -> List[Segment]:
        """
        提取段落内容

        Args:
            lines: 文本行列表
            boundaries: 段落边界列表

        Returns:
            List[Segment]: 段落列表
        """
        segments = []

        # 如果没有识别到边界，将整个文本作为"其他"段落
        if not boundaries:
            content = "\n".join(lines).strip()
            if content:
                segments.append(Segment(
                    segment_type=SectionType.OTHER,
                    content=content,
                    position=0,
                ))
            return segments

        # 处理第一个边界之前的内容（通常是个人信息）
        if boundaries[0][0] > 0:
            personal_content = "\n".join(lines[:boundaries[0][0]]).strip()
            if personal_content:
                segments.append(Segment(
                    segment_type=SectionType.PERSONAL_INFO,
                    content=personal_content,
                    title="个人信息",
                    position=0,
                ))

        # 提取每个段落
        for idx, (start_line, section_type, title) in enumerate(boundaries):
            # 确定段落结束行
            if idx + 1 < len(boundaries):
                end_line = boundaries[idx + 1][0]
            else:
                end_line = len(lines)

            # 提取段落内容（跳过标题行）
            content_lines = lines[start_line + 1:end_line]
            content = "\n".join(content_lines).strip()

            if content:
                # 提取组织机构和日期
                organization = self._extract_organization(content, section_type)
                start_date, end_date = self._extract_dates(content)

                segments.append(Segment(
                    segment_type=section_type,
                    content=content,
                    title=title,
                    organization=organization,
                    start_date=start_date,
                    end_date=end_date,
                    position=start_line,
                ))

        return segments

    def _extract_organization(
        self, content: str, section_type: SectionType
    ) -> Optional[str]:
        """
        提取组织机构名称

        Args:
            content: 段落内容
            section_type: 段落类型

        Returns:
            Optional[str]: 组织机构名称
        """
        # 简单启发式：第一行通常是组织机构
        first_line = content.split("\n")[0].strip()

        # 移除日期
        for pattern in self.DATE_PATTERNS:
            first_line = re.sub(pattern, "", first_line).strip()

        # 移除常见的职位后缀
        position_suffixes = ["工程师", "经理", "总监", "主管", "专员", "实习"]
        for suffix in position_suffixes:
            if suffix in first_line:
                first_line = first_line.split(suffix)[0].strip()
                break

        return first_line if first_line else None

    def _extract_dates(self, content: str) -> Tuple[Optional[str], Optional[str]]:
        """
        提取日期范围

        Args:
            content: 段落内容

        Returns:
            Tuple[Optional[str], Optional[str]]: (开始日期, 结束日期)
        """
        for pattern in self.DATE_PATTERNS:
            match = re.search(pattern, content)
            if match:
                groups = match.groups()
                start_date = groups[0] if groups[0] else None
                end_date = groups[2] if len(groups) > 2 and groups[2] else None

                # 格式化日期
                if start_date:
                    if len(groups) > 1 and groups[1]:
                        start_date = f"{start_date}-{groups[1].zfill(2)}"
                if end_date and len(groups) > 3 and groups[3]:
                    end_date = f"{end_date}-{groups[3].zfill(2)}"

                return start_date, end_date

        return None, None

    def _detect_overlaps(self, segments: List[Segment]) -> List[OverlapWarning]:
        """
        检测段落时间重叠

        Args:
            segments: 段落列表

        Returns:
            List[OverlapWarning]: 重叠警告列表
        """
        warnings = []

        # 转换日期为可比较的格式
        def parse_date(date_str: Optional[str]) -> Optional[datetime]:
            if not date_str or date_str in ["至今", "现在"]:
                return None
            try:
                # 尝试解析 YYYY-MM 格式
                if "-" in date_str:
                    return datetime.strptime(date_str, "%Y-%m")
                # 尝试解析 YYYY 格式
                return datetime.strptime(date_str, "%Y")
            except ValueError:
                return None

        # 检测工作经历和项目经历的重叠
        experience_segments = [
            (i, s) for i, s in enumerate(segments)
            if s.segment_type in [SectionType.EXPERIENCE, SectionType.PROJECT]
        ]

        for i in range(len(experience_segments)):
            for j in range(i + 1, len(experience_segments)):
                idx1, seg1 = experience_segments[i]
                idx2, seg2 = experience_segments[j]

                start1 = parse_date(seg1.start_date)
                end1 = parse_date(seg1.end_date)
                start2 = parse_date(seg2.start_date)
                end2 = parse_date(seg2.end_date)

                # 检查时间重叠
                if start1 and start2:
                    # 如果两个段落都有开始日期，检查是否重叠
                    if not end1 and not end2:
                        # 两个都没有结束日期，可能重叠
                        warnings.append(OverlapWarning(
                            segment1_index=idx1,
                            segment2_index=idx2,
                            overlap_type="time_overlap",
                            message=f"段落 {idx1} 和段落 {idx2} 可能时间重叠",
                        ))

        return warnings


# 全局段落切分器实例
segmenter = Segmenter()


def get_segmenter() -> Segmenter:
    """获取段落切分器实例"""
    return segmenter
