"""
智能招聘 RAG 推荐系统 - Chunk Builder

变更 (Tier L): 从 ResumeStructured 结构化数据构建 Chunk，不再从 raw_text 按关键词+字符数切割。
每条结构化记录（工作经历/项目/教育/技能组）→ 一个 Small Chunk，
携带完整 metadata（候选人级 + Chunk 级），支持 Milvus 标量预过滤。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)

EDUCATION_LEVEL_MAP: Dict[str, int] = {
    "高中": 0, "中专": 0,
    "大专": 1,
    "本科": 2,
    "硕士": 3,
    "博士": 4,
}


class ChunkLevel(str, Enum):
    SMALL = "small"
    PARENT = "parent"
    FULL = "full"


class SectionType(str, Enum):
    PERSONAL_INFO = "personal_info"
    EDUCATION = "education"
    EXPERIENCE = "experience"
    PROJECT = "project"
    SKILL = "skill"
    OTHER = "other"


@dataclass
class ChunkSchema:
    chunk_id: str
    resume_id: str
    chunk_level: ChunkLevel
    parent_chunk_id: Optional[str] = None
    section_type: Optional[SectionType] = None
    content: str = ""
    char_count: int = 0
    sequence_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "resume_id": self.resume_id,
            "chunk_level": self.chunk_level.value,
            "parent_chunk_id": self.parent_chunk_id or "",
            "section_type": self.section_type.value if self.section_type else "",
            "content": self.content,
            "char_count": self.char_count,
            "sequence_index": self.sequence_index,
            "metadata": self.metadata,
        }


@dataclass
class ChunkBuildResult:
    chunks: List[ChunkSchema] = field(default_factory=list)
    full_chunk: Optional[ChunkSchema] = None
    parent_chunks: List[ChunkSchema] = field(default_factory=list)
    small_chunks: List[ChunkSchema] = field(default_factory=list)
    total_chunks: int = 0


class ChunkBuilder:

    def generate_chunks(
        self,
        resume_id: str,
        resume_structured: Any,
        raw_text: str = "",
    ) -> List[ChunkSchema]:
        """
        从 ResumeStructured 结构化数据构建多粒度 Chunk。

        Args:
            resume_id: 简历 ID
            resume_structured: LLM 提取的结构化数据 (ResumeStructured)
            raw_text: 原始文本（降级用）
        """
        chunks: List[ChunkSchema] = []
        seq = 0

        # 提取候选人级 metadata
        personal = getattr(resume_structured, "personal_info", None)
        education_list = getattr(resume_structured, "education_list", []) or []
        experience_list = getattr(resume_structured, "experience_list", []) or []
        project_list = getattr(resume_structured, "project_list", []) or []
        skill_list = getattr(resume_structured, "skill_list", []) or []

        candidate_meta = self._build_candidate_metadata(personal, education_list, experience_list)
        candidate_meta["skills_normalized"] = [
            getattr(s, "name", str(s)).lower() for s in skill_list
        ]
        candidate_meta["skills_original"] = [
            getattr(s, "name", str(s)) for s in skill_list
        ]
        candidate_meta["total_experience_entries"] = len(experience_list)
        candidate_meta["total_project_entries"] = len(project_list)

        # 1. Full Resume Chunk
        summary = getattr(personal, "summary", None) if personal else None
        full_content = summary or raw_text or "无内容"
        full = self._make_chunk(
            resume_id, ChunkLevel.FULL, seq, "full-00",
            full_content, None, None, candidate_meta,
        )
        chunks.append(full)
        seq += 1

        # 1.1 PersonalInfo Small Chunk (使职称/年限/城市可被语义检索命中)
        pi_parts = []
        if candidate_meta.get("current_title"):
            pi_parts.append(candidate_meta["current_title"])
        if candidate_meta.get("years_of_experience"):
            pi_parts.append(f"{candidate_meta['years_of_experience']}年经验")
        if candidate_meta.get("city"):
            pi_parts.append(candidate_meta["city"])
        if candidate_meta.get("candidate_name"):
            pi_parts.append(candidate_meta["candidate_name"])
        if candidate_meta.get("current_company"):
            pi_parts.append(candidate_meta["current_company"])
        if pi_parts:
            pi_content = " | ".join(pi_parts)
            pi_parent_id = f"{resume_id}:parent:{seq:04d}"
            chunks.append(self._make_chunk(
                resume_id, ChunkLevel.PARENT, seq, pi_parent_id,
                pi_content, SectionType.PERSONAL_INFO, None, dict(candidate_meta),
            ))
            seq += 1
            chunks.append(self._make_chunk(
                resume_id, ChunkLevel.SMALL, seq,
                self._chunk_id(resume_id, ChunkLevel.SMALL, seq),
                pi_content, SectionType.PERSONAL_INFO, pi_parent_id,
                {**candidate_meta, "entry_type": "personal_info"},
            ))
            seq += 1

        # 2. Education section
        if education_list:
            parent_id = f"{resume_id}:parent:{seq:04d}"
            parent_content, parent_meta = self._build_parent_section(
                education_list, SectionType.EDUCATION, candidate_meta,
                fmt_fn=lambda e: self._fmt_education(e),
            )
            chunks.append(self._make_chunk(
                resume_id, ChunkLevel.PARENT, seq, parent_id,
                parent_content, SectionType.EDUCATION, None, parent_meta,
            ))
            seq += 1
            for e in education_list:
                chunks.append(self._make_chunk(
                    resume_id, ChunkLevel.SMALL, seq, self._chunk_id(resume_id, ChunkLevel.SMALL, seq),
                    self._fmt_education(e), SectionType.EDUCATION, parent_id,
                    {**candidate_meta, "organization": getattr(e, "school", ""),
                     "start_date": getattr(e, "start_date", ""),
                     "end_date": getattr(e, "end_date", ""),
                     "entry_type": "education"},
                ))
                seq += 1

        # 3. Experience section
        if experience_list:
            parent_id = f"{resume_id}:parent:{seq:04d}"
            parent_content, parent_meta = self._build_parent_section(
                experience_list, SectionType.EXPERIENCE, candidate_meta,
                fmt_fn=lambda e: self._fmt_experience(e),
            )
            chunks.append(self._make_chunk(
                resume_id, ChunkLevel.PARENT, seq, parent_id,
                parent_content, SectionType.EXPERIENCE, None, parent_meta,
            ))
            seq += 1
            for e in experience_list:
                content = self._fmt_experience(e)
                chunks.append(self._make_chunk(
                    resume_id, ChunkLevel.SMALL, seq, self._chunk_id(resume_id, ChunkLevel.SMALL, seq),
                    content, SectionType.EXPERIENCE, parent_id,
                    {**candidate_meta,
                     "organization": getattr(e, "company", ""),
                     "title": getattr(e, "title", ""),
                     "start_date": getattr(e, "start_date", ""),
                     "end_date": getattr(e, "end_date", ""),
                     "entry_type": "experience"},
                ))
                seq += 1

        # 4. Project section
        if project_list:
            parent_id = f"{resume_id}:parent:{seq:04d}"
            parent_content, parent_meta = self._build_parent_section(
                project_list, SectionType.PROJECT, candidate_meta,
                fmt_fn=lambda e: self._fmt_project(e),
            )
            chunks.append(self._make_chunk(
                resume_id, ChunkLevel.PARENT, seq, parent_id,
                parent_content, SectionType.PROJECT, None, parent_meta,
            ))
            seq += 1
            for e in project_list:
                chunks.append(self._make_chunk(
                    resume_id, ChunkLevel.SMALL, seq, self._chunk_id(resume_id, ChunkLevel.SMALL, seq),
                    self._fmt_project(e), SectionType.PROJECT, parent_id,
                    {**candidate_meta,
                     "organization": getattr(e, "name", ""),
                     "title": getattr(e, "role", ""),
                     "tech_stack": getattr(e, "tech_stack", []),
                     "start_date": getattr(e, "start_date", ""),
                     "end_date": getattr(e, "end_date", ""),
                     "entry_type": "project"},
                ))
                seq += 1

        # 5. Skill section
        if skill_list:
            parent_id = f"{resume_id}:parent:{seq:04d}"
            parent_content = "、".join(
                f"{getattr(s, 'name', str(s))}"
                f"({getattr(s, 'proficiency', '')},"
                f"{getattr(s, 'years_of_experience', '')}年)"
                for s in skill_list
            )
            chunks.append(self._make_chunk(
                resume_id, ChunkLevel.PARENT, seq, parent_id,
                parent_content, SectionType.SKILL, None, dict(candidate_meta),
            ))
            seq += 1
            # Group skills by category
            by_cat: Dict[str, List[Any]] = {}
            for s in skill_list:
                cat = getattr(s, "category", "other") or "other"
                by_cat.setdefault(cat, []).append(s)
            for cat, skills in by_cat.items():
                skill_content = "、".join(
                    f"{getattr(s, 'name', str(s))}"
                    f"({getattr(s, 'proficiency', '')},"
                    f"{getattr(s, 'years_of_experience', '')}年)"
                    for s in skills
                )
                chunks.append(self._make_chunk(
                    resume_id, ChunkLevel.SMALL, seq, self._chunk_id(resume_id, ChunkLevel.SMALL, seq),
                    skill_content, SectionType.SKILL, parent_id,
                    {**candidate_meta, "skill_category": cat, "entry_type": "skill"},
                ))
                seq += 1

        logger.info(f"Chunk 构建完成: {len(chunks)} 个 (resume_id={resume_id})")
        return chunks

    def _build_candidate_metadata(
        self, personal: Any, education_list: List[Any], experience_list: List[Any],
    ) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "candidate_name": getattr(personal, "full_name", "") if personal else "",
            "years_of_experience": int(getattr(personal, "years_of_experience", 0) or 0),
            "city": getattr(personal, "city", "") if personal else "",
            "gender": getattr(personal, "gender", "") if personal else "",
            "current_title": getattr(personal, "current_title", "") if personal else "",
            "current_company": getattr(personal, "current_company", "") if personal else "",
        }

        # 最高学历
        max_level = 0
        max_degree = ""
        for e in education_list:
            degree = getattr(e, "degree", "") or ""
            level = EDUCATION_LEVEL_MAP.get(degree, 0)
            if level > max_level:
                max_level = level
                max_degree = degree
        meta["highest_education_level"] = max_level
        meta["highest_education"] = max_degree
        meta["is_985"] = any(getattr(e, "is_985", False) for e in education_list)
        meta["is_211"] = any(getattr(e, "is_211", False) for e in education_list)

        # 行业
        if experience_list:
            latest = experience_list[0]
            meta["industry"] = getattr(latest, "industry", "") or ""

        return meta

    def _build_parent_section(
        self, entries: List[Any], stype: SectionType,
        candidate_meta: Dict[str, Any], fmt_fn,
    ) -> tuple:
        lines = [fmt_fn(e) for e in entries]
        content = "\n\n".join(lines)
        meta = dict(candidate_meta)
        meta["section_type"] = stype.value
        return content, meta

    def _fmt_education(self, e: Any) -> str:
        school = getattr(e, "school", "")
        major = getattr(e, "major", "")
        degree = getattr(e, "degree", "")
        s_date = getattr(e, "start_date", "")
        e_date = getattr(e, "end_date", "")
        desc = getattr(e, "description", "")
        parts = [f"{school} | {major} | {degree}"]
        if s_date or e_date:
            parts.append(f"{s_date} ~ {e_date}")
        if desc:
            parts.append(desc)
        return " | ".join(p for p in parts if p)

    def _fmt_experience(self, e: Any) -> str:
        company = getattr(e, "company", "")
        title = getattr(e, "title", "")
        s_date = getattr(e, "start_date", "")
        e_date = getattr(e, "end_date", "")
        desc = getattr(e, "description", "")
        achievements = getattr(e, "achievements", []) or []
        parts = [f"{company} | {title} | {s_date} ~ {e_date}"]
        if desc:
            parts.append(desc)
        if achievements:
            parts.append("成就: " + "; ".join(achievements))
        return "\n".join(parts)

    def _fmt_project(self, e: Any) -> str:
        name = getattr(e, "name", "")
        role = getattr(e, "role", "")
        s_date = getattr(e, "start_date", "")
        e_date = getattr(e, "end_date", "")
        desc = getattr(e, "description", "")
        tech_stack = getattr(e, "tech_stack", []) or []
        parts = [f"{name} | {role} | {s_date} ~ {e_date}"]
        if desc:
            parts.append(desc)
        if tech_stack:
            parts.append("技术栈: " + ", ".join(tech_stack))
        return "\n".join(parts)

    def _chunk_id(self, resume_id: str, level: ChunkLevel, seq: int) -> str:
        return f"{resume_id}:{level.value}:{seq:04d}"

    def _make_chunk(
        self, resume_id: str, level: ChunkLevel, seq: int, chunk_id: str,
        content: str, section_type: Optional[SectionType],
        parent_chunk_id: Optional[str], metadata: Dict[str, Any],
    ) -> ChunkSchema:
        return ChunkSchema(
            chunk_id=chunk_id,
            resume_id=resume_id,
            chunk_level=level,
            parent_chunk_id=parent_chunk_id,
            section_type=section_type,
            content=content,
            char_count=len(content),
            sequence_index=seq,
            metadata=metadata,
        )


# 全局单例
_chunk_builder: Optional[ChunkBuilder] = None


def get_chunk_builder() -> ChunkBuilder:
    global _chunk_builder
    if _chunk_builder is None:
        _chunk_builder = ChunkBuilder()
    return _chunk_builder
