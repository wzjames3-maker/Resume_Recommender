"""
智能招聘 RAG 推荐系统 - Chunk 层级构建器

构建 Multi-Level Chunk（Small/Parent/Full 三层）
"""

from enum import Enum
from typing import Any, Dict, List, Optional

import re

from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.resume_parser.segmenter import SectionType, Segment

logger = get_logger("chunk_builder")


class ChunkLevel(str, Enum):
    """Chunk 粒度级别"""

    SMALL = "small"  # Small Chunk: 单句或小段落 (50~200 字符)
    PARENT = "parent"  # Parent Chunk: 完整 Section
    FULL = "full"  # Full Resume: 整份简历


class ChunkSchema(BaseModel):
    """多粒度 Chunk"""

    chunk_id: str = Field(..., description="Chunk 唯一 ID")
    resume_id: str = Field(..., description="所属简历 ID")
    chunk_level: ChunkLevel = Field(..., description="Chunk 粒度级别")
    parent_chunk_id: Optional[str] = Field(None, description="父 Chunk ID")
    section_type: Optional[SectionType] = Field(None, description="所属 Section 类型")
    content: str = Field(..., description="Chunk 文本内容")
    char_count: int = Field(0, description="字符数")
    sequence_index: int = Field(0, description="在简历中的顺序索引")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class ChunkBuildResult(BaseModel):
    """Chunk 构建结果"""

    chunks: List[ChunkSchema] = Field(default_factory=list, description="Chunk 列表")
    full_chunk: Optional[ChunkSchema] = Field(None, description="Full Resume Chunk")
    parent_chunks: List[ChunkSchema] = Field(default_factory=list, description="Parent Chunk 列表")
    small_chunks: List[ChunkSchema] = Field(default_factory=list, description="Small Chunk 列表")
    total_chunks: int = Field(0, description="Chunk 总数")


class ChunkBuilder:
    """Chunk 层级构建器"""

    # Small Chunk 目标大小范围
    SMALL_CHUNK_MIN_SIZE = 50  # 最小字符数
    SMALL_CHUNK_MAX_SIZE = 200  # 最大字符数

    def build(
        self,
        segments: List[Segment],
        resume_id: str,
        full_text: str,
    ) -> ChunkBuildResult:
        """
        构建 Multi-Level Chunk

        Args:
            segments: 语义段落列表
            resume_id: 简历 ID
            full_text: 简历全文

        Returns:
            ChunkBuildResult: Chunk 构建结果
        """
        chunks = []
        parent_chunks = []
        small_chunks = []

        # 1. 构建 Full Resume Chunk
        full_chunk = self._build_full_chunk(full_text, resume_id, 0)
        chunks.append(full_chunk)

        # 2. 构建 Parent Chunks 和 Small Chunks
        parent_index = 0
        small_index = 0

        for segment in segments:
            # 构建 Parent Chunk
            parent_chunk_id = self._generate_chunk_id(
                resume_id, ChunkLevel.PARENT, parent_index
            )
            parent_chunk = self._build_parent_chunk(
                segment, resume_id, parent_chunk_id, parent_index
            )
            parent_chunks.append(parent_chunk)
            chunks.append(parent_chunk)

            # 构建 Small Chunks
            segment_small_chunks = self._build_small_chunks(
                segment, resume_id, parent_chunk_id, small_index
            )
            small_chunks.extend(segment_small_chunks)
            chunks.extend(segment_small_chunks)

            parent_index += 1
            small_index += len(segment_small_chunks)

        logger.info(
            f"Chunk 构建完成: 1 Full + {len(parent_chunks)} Parent + "
            f"{len(small_chunks)} Small = {len(chunks)} 个 Chunk"
        )

        return ChunkBuildResult(
            chunks=chunks,
            full_chunk=full_chunk,
            parent_chunks=parent_chunks,
            small_chunks=small_chunks,
            total_chunks=len(chunks),
        )

    def _generate_chunk_id(
        self, resume_id: str, level: ChunkLevel, index: int
    ) -> str:
        """
        生成 Chunk ID

        格式: {resume_id}:{level}:{index}

        Args:
            resume_id: 简历 ID
            level: Chunk 级别
            index: 索引

        Returns:
            str: Chunk ID
        """
        return f"{resume_id}:{level.value}:{index}"

    def _build_full_chunk(
        self, content: str, resume_id: str, index: int
    ) -> ChunkSchema:
        """
        构建 Full Resume Chunk

        Args:
            content: 简历全文
            resume_id: 简历 ID
            index: 索引

        Returns:
            ChunkSchema: Full Chunk
        """
        chunk_id = self._generate_chunk_id(resume_id, ChunkLevel.FULL, index)

        return ChunkSchema(
            chunk_id=chunk_id,
            resume_id=resume_id,
            chunk_level=ChunkLevel.FULL,
            parent_chunk_id=None,
            section_type=None,
            content=content,
            char_count=len(content),
            sequence_index=index,
        )

    def _build_parent_chunk(
        self,
        segment: Segment,
        resume_id: str,
        chunk_id: str,
        index: int,
    ) -> ChunkSchema:
        """
        构建 Parent Chunk

        Args:
            segment: 语义段落
            resume_id: 简历 ID
            chunk_id: Chunk ID
            index: 索引

        Returns:
            ChunkSchema: Parent Chunk
        """
        return ChunkSchema(
            chunk_id=chunk_id,
            resume_id=resume_id,
            chunk_level=ChunkLevel.PARENT,
            parent_chunk_id=None,  # Parent Chunk 没有父 Chunk
            section_type=segment.segment_type,
            content=segment.content,
            char_count=len(segment.content),
            sequence_index=index,
            metadata={
                "title": segment.title,
                "organization": segment.organization,
                "start_date": segment.start_date,
                "end_date": segment.end_date,
            },
        )

    def _build_small_chunks(
        self,
        segment: Segment,
        resume_id: str,
        parent_chunk_id: str,
        start_index: int,
    ) -> List[ChunkSchema]:
        """
        构建 Small Chunks

        将语义段落切分为单句级粒度（50~200 字符）

        Args:
            segment: 语义段落
            resume_id: 简历 ID
            parent_chunk_id: 父 Chunk ID
            start_index: 起始索引

        Returns:
            List[ChunkSchema]: Small Chunk 列表
        """
        small_chunks = []

        # 按句子切分
        sentences = self._split_into_sentences(segment.content)

        # 合并短句子，拆分长句子
        merged_chunks = self._merge_and_split_chunks(sentences)

        # 创建 Small Chunks
        for i, chunk_content in enumerate(merged_chunks):
            chunk_id = self._generate_chunk_id(
                resume_id, ChunkLevel.SMALL, start_index + i
            )

            small_chunks.append(ChunkSchema(
                chunk_id=chunk_id,
                resume_id=resume_id,
                chunk_level=ChunkLevel.SMALL,
                parent_chunk_id=parent_chunk_id,
                section_type=segment.segment_type,
                content=chunk_content,
                char_count=len(chunk_content),
                sequence_index=start_index + i,
                metadata={
                    "parent_title": segment.title,
                    "parent_organization": segment.organization,
                },
            ))

        return small_chunks

    def _split_into_sentences(self, text: str) -> List[str]:
        """
        将文本切分为句子

        Args:
            text: 文本内容

        Returns:
            List[str]: 句子列表
        """
        # 按换行符和句号分割
        sentences = []

        # 先按换行分割
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 按句号、分号分割（中文标点）
            parts = re.split(r"[。；;]", line)

            for part in parts:
                part = part.strip()
                if part:
                    sentences.append(part)

        return sentences

    def _merge_and_split_chunks(self, sentences: List[str]) -> List[str]:
        """
        合并短句子，拆分长句子

        Args:
            sentences: 句子列表

        Returns:
            List[str]: 处理后的 Chunk 列表
        """
        chunks = []
        current_chunk = ""

        for sentence in sentences:
            # 如果当前句子太长，需要拆分
            if len(sentence) > self.SMALL_CHUNK_MAX_SIZE:
                # 先保存当前 chunk
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""

                # 拆分长句子
                split_parts = self._split_long_sentence(sentence)
                chunks.extend(split_parts)
                continue

            # 如果加上当前句子会超过最大长度，保存当前 chunk
            if len(current_chunk) + len(sentence) > self.SMALL_CHUNK_MAX_SIZE:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence
            else:
                # 合并句子
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence

        # 保存最后一个 chunk
        if current_chunk:
            chunks.append(current_chunk)

        # 合并过短的 chunks
        merged_chunks = []
        temp_chunk = ""

        for chunk in chunks:
            if len(chunk) < self.SMALL_CHUNK_MIN_SIZE:
                # 尝试与前一个 chunk 合并
                if temp_chunk and len(temp_chunk) + len(chunk) <= self.SMALL_CHUNK_MAX_SIZE:
                    temp_chunk += " " + chunk
                else:
                    if temp_chunk:
                        merged_chunks.append(temp_chunk)
                    temp_chunk = chunk
            else:
                if temp_chunk:
                    merged_chunks.append(temp_chunk)
                    temp_chunk = ""
                merged_chunks.append(chunk)

        if temp_chunk:
            merged_chunks.append(temp_chunk)

        return merged_chunks if merged_chunks else chunks

    def _split_long_sentence(self, sentence: str) -> List[str]:
        """
        拆分长句子

        Args:
            sentence: 长句子

        Returns:
            List[str]: 拆分后的句子列表
        """
        parts = []

        # 按逗号、顿号分割
        sub_parts = re.split(r"[，、,]", sentence)

        current_part = ""
        for part in sub_parts:
            part = part.strip()
            if not part:
                continue

            if len(current_part) + len(part) <= self.SMALL_CHUNK_MAX_SIZE:
                if current_part:
                    current_part += "，" + part
                else:
                    current_part = part
            else:
                if current_part:
                    parts.append(current_part)
                current_part = part

        if current_part:
            parts.append(current_part)

        return parts if parts else [sentence]



# 全局 Chunk 构建器实例
chunk_builder = ChunkBuilder()


def get_chunk_builder() -> ChunkBuilder:
    """获取 Chunk 构建器实例"""
    return chunk_builder
