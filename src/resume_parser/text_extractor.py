"""
智能招聘 RAG 推荐系统 - 文本提取模块

支持从 PDF、DOCX、JSON 格式简历中提取文本内容
"""

import io
import json
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import docx
import pdfplumber
from pydantic import BaseModel, Field

from src.common.config import get_settings
from src.common.errors import ErrorCode, ValidationError
from src.common.logger import get_logger

logger = get_logger("text_extractor")


class FileType(str, Enum):
    """文件类型"""

    PDF = "pdf"
    DOCX = "docx"
    JSON = "json"
    IMAGE = "image"


class ExtractionStatus(str, Enum):
    """提取状态"""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class ExtractedDocument(BaseModel):
    """提取的文档结构"""

    raw_text: str = Field(..., description="提取的原始文本")
    page_texts: List[str] = Field(default_factory=list, description="每页文本列表")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="文档元数据")
    status: ExtractionStatus = Field(ExtractionStatus.SUCCESS, description="提取状态")
    warnings: List[str] = Field(default_factory=list, description="警告信息列表")
    extraction_time: datetime = Field(
        default_factory=datetime.now(timezone.utc), description="提取时间"
    )
    duration_ms: Optional[int] = Field(None, description="提取耗时（毫秒）")


class TextExtractor:
    """文本提取器"""

    def __init__(self):
        """初始化文本提取器"""
        self.settings = get_settings()
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        self.timeout = 30  # 30 秒超时

    def extract(
        self,
        file_content: bytes,
        file_name: str,
        file_type: Optional[FileType] = None,
    ) -> ExtractedDocument:
        """
        提取文件文本内容

        Args:
            file_content: 文件内容（二进制）
            file_name: 文件名
            file_type: 文件类型（可选，自动检测）

        Returns:
            ExtractedDocument: 提取的文档结构

        Raises:
            ValidationError: 文件格式错误、大小超限、加密保护等
        """
        start_time = time.time()

        # 检查文件大小
        if len(file_content) > self.max_file_size:
            raise ValidationError(
                error_code=ErrorCode.RESUME_004,
                detail=f"文件大小超过限制: {len(file_content)} bytes > {self.max_file_size} bytes",
            )

        # 检查空文件
        if len(file_content) == 0:
            raise ValidationError(
                error_code=ErrorCode.SYS_001,
                detail="文件为空（0 字节）",
            )

        # 自动检测文件类型
        if file_type is None:
            file_type = self._detect_file_type(file_name, file_content)

        # 根据文件类型提取文本
        try:
            if file_type == FileType.PDF:
                result = self._extract_pdf(file_content, file_name)
            elif file_type == FileType.DOCX:
                result = self._extract_docx(file_content, file_name)
            elif file_type == FileType.JSON:
                result = self._extract_json(file_content, file_name)
            else:
                raise ValidationError(
                    error_code=ErrorCode.RESUME_003,
                    detail=f"不支持的文件格式: {file_type}",
                )
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"文本提取失败: {str(e)}")
            raise ValidationError(
                error_code=ErrorCode.RESUME_002,
                detail=f"文本提取失败: {str(e)}",
            )

        # 计算耗时
        duration_ms = int((time.time() - start_time) * 1000)
        result.duration_ms = duration_ms
        result.extraction_time = datetime.now(timezone.utc)

        logger.info(
            f"文本提取完成: {file_name}, 类型: {file_type}, "
            f"耗时: {duration_ms}ms, 文本长度: {len(result.raw_text)}"
        )

        return result

    def _detect_file_type(self, file_name: str, file_content: bytes) -> FileType:
        """
        自动检测文件类型

        Args:
            file_name: 文件名
            file_content: 文件内容

        Returns:
            FileType: 文件类型
        """
        # 通过文件扩展名检测
        suffix = Path(file_name).suffix.lower()

        if suffix == ".pdf":
            return FileType.PDF
        elif suffix in (".docx", ".doc"):
            if suffix == ".doc":
                raise ValidationError(
                    error_code=ErrorCode.RESUME_003,
                    detail="不支持旧版 .doc 格式，请转换为 .docx 后重新上传",
                )
            return FileType.DOCX
        elif suffix == ".json":
            return FileType.JSON
        elif suffix in (".jpg", ".jpeg", ".png"):
            return FileType.IMAGE

        # 通过文件头检测
        if file_content[:4] == b"%PDF":
            return FileType.PDF
        elif file_content[:4] == b"PK\x03\x04":
            # ZIP 格式，可能是 DOCX
            return FileType.DOCX

        raise ValidationError(
            error_code=ErrorCode.RESUME_003,
            detail=f"无法识别的文件格式: {file_name}",
        )

    def _extract_pdf(self, file_content: bytes, file_name: str) -> ExtractedDocument:
        """
        提取 PDF 文本内容

        Args:
            file_content: PDF 文件内容
            file_name: 文件名

        Returns:
            ExtractedDocument: 提取的文档结构
        """
        page_texts = []
        warnings = []

        try:
            # 优先使用 pdfplumber
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                # 检查是否加密
                if pdf.is_encrypted:
                    raise ValidationError(
                        error_code=ErrorCode.RESUME_002,
                        detail="PDF 文件已加密，请提供解密后的文件",
                    )

                # 提取每页文本
                for page_num, page in enumerate(pdf.pages, 1):
                    try:
                        text = page.extract_text()
                        if text:
                            # 清理文本
                            text = self._clean_text(text)
                            page_texts.append(text)
                        else:
                            page_texts.append("")
                            warnings.append(f"第 {page_num} 页未提取到文本")
                    except Exception as e:
                        page_texts.append("")
                        warnings.append(f"第 {page_num} 页提取失败: {str(e)}")

                # 合并所有页面文本
                raw_text = "\n\n".join(page_texts)

                # 去除页眉页脚重复内容
                raw_text = self._remove_header_footer(raw_text)

                return ExtractedDocument(
                    raw_text=raw_text,
                    page_texts=page_texts,
                    metadata={
                        "file_name": file_name,
                        "file_type": "pdf",
                        "file_size": len(file_content),
                        "page_count": len(pdf.pages),
                        "extraction_tool": "pdfplumber",
                    },
                    warnings=warnings,
                )

        except ValidationError:
            raise
        except Exception as e:
            logger.warning(f"pdfplumber 提取失败，尝试 PyPDF2: {str(e)}")
            return self._extract_pdf_with_pypdf2(file_content, file_name)

    def _extract_pdf_with_pypdf2(
        self, file_content: bytes, file_name: str
    ) -> ExtractedDocument:
        """
        使用 PyPDF2 提取 PDF 文本内容（降级方案）

        Args:
            file_content: PDF 文件内容
            file_name: 文件名

        Returns:
            ExtractedDocument: 提取的文档结构
        """
        from PyPDF2 import PdfReader

        page_texts = []
        warnings = []

        try:
            reader = PdfReader(io.BytesIO(file_content))

            # 检查是否加密
            if reader.is_encrypted:
                raise ValidationError(
                    error_code=ErrorCode.RESUME_002,
                    detail="PDF 文件已加密，请提供解密后的文件",
                )

            # 提取每页文本
            for page_num, page in enumerate(reader.pages, 1):
                try:
                    text = page.extract_text()
                    if text:
                        text = self._clean_text(text)
                        page_texts.append(text)
                    else:
                        page_texts.append("")
                        warnings.append(f"第 {page_num} 页未提取到文本")
                except Exception as e:
                    page_texts.append("")
                    warnings.append(f"第 {page_num} 页提取失败: {str(e)}")

            # 合并所有页面文本
            raw_text = "\n\n".join(page_texts)

            return ExtractedDocument(
                raw_text=raw_text,
                page_texts=page_texts,
                metadata={
                    "file_name": file_name,
                    "file_type": "pdf",
                    "file_size": len(file_content),
                    "page_count": len(reader.pages),
                    "extraction_tool": "PyPDF2",
                },
                warnings=warnings,
            )

        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(
                error_code=ErrorCode.RESUME_002,
                detail=f"PDF 提取失败: {str(e)}",
            )

    def _extract_docx(self, file_content: bytes, file_name: str) -> ExtractedDocument:
        """
        提取 DOCX 文本内容

        Args:
            file_content: DOCX 文件内容
            file_name: 文件名

        Returns:
            ExtractedDocument: 提取的文档结构
        """
        warnings = []

        try:
            doc = docx.Document(io.BytesIO(file_content))

            # 提取段落文本
            paragraphs = []
            for para in doc.paragraphs:
                if para.text.strip():
                    paragraphs.append(para.text.strip())

            # 提取表格文本
            tables_text = []
            for table in doc.tables:
                table_rows = []
                for row in table.rows:
                    row_cells = [cell.text.strip() for cell in row.cells]
                    table_rows.append(" | ".join(row_cells))
                if table_rows:
                    tables_text.append("\n".join(table_rows))

            # 合并文本
            all_text = paragraphs + tables_text
            raw_text = "\n\n".join(all_text)

            # 清理文本
            raw_text = self._clean_text(raw_text)

            return ExtractedDocument(
                raw_text=raw_text,
                page_texts=[raw_text],  # DOCX 没有明确的页面概念
                metadata={
                    "file_name": file_name,
                    "file_type": "docx",
                    "file_size": len(file_content),
                    "paragraph_count": len(paragraphs),
                    "table_count": len(tables_text),
                    "extraction_tool": "python-docx",
                },
                warnings=warnings,
            )

        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(
                error_code=ErrorCode.RESUME_002,
                detail=f"DOCX 提取失败: {str(e)}",
            )

    def _extract_json(self, file_content: bytes, file_name: str) -> ExtractedDocument:
        """
        提取 JSON 格式简历

        Args:
            file_content: JSON 文件内容
            file_name: 文件名

        Returns:
            ExtractedDocument: 提取的文档结构
        """
        try:
            # 解析 JSON
            data = json.loads(file_content.decode("utf-8"))

            # 转换为文本格式
            raw_text = json.dumps(data, ensure_ascii=False, indent=2)

            return ExtractedDocument(
                raw_text=raw_text,
                page_texts=[raw_text],
                metadata={
                    "file_name": file_name,
                    "file_type": "json",
                    "file_size": len(file_content),
                    "extraction_tool": "json",
                    "is_structured": True,
                },
            )

        except json.JSONDecodeError as e:
            raise ValidationError(
                error_code=ErrorCode.RESUME_002,
                detail=f"JSON 解析失败: {str(e)}",
            )
        except Exception as e:
            raise ValidationError(
                error_code=ErrorCode.RESUME_002,
                detail=f"JSON 提取失败: {str(e)}",
            )

    def _clean_text(self, text: str) -> str:
        """
        清理提取的文本

        Args:
            text: 原始文本

        Returns:
            str: 清理后的文本
        """
        # 合并跨页断行
        text = text.replace("-\n", "")

        # 移除多余的空白字符
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line:
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    def _remove_header_footer(self, text: str) -> str:
        """Remove repeated headers/footers from extracted text."""
        lines = text.split(chr(10))
        if len(lines) < 5:
            return text
        cleaned = []
        first_line = lines[0].strip()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.isdigit():
                continue
            if i > 0 and stripped and stripped == first_line:
                continue
            cleaned.append(line)
        return chr(10).join(cleaned)

# 全局文本提取器实例
text_extractor = TextExtractor()


def get_text_extractor() -> TextExtractor:
    """获取文本提取器实例"""
    return text_extractor
