"""
智能招聘 RAG 推荐系统 - 文本提取模块测试
"""

import json
from pathlib import Path

import pytest

from src.resume_parser.text_extractor import (
    ExtractedDocument,
    ExtractionStatus,
    FileType,
    TextExtractor,
    get_text_extractor,
)


@pytest.fixture
def extractor():
    """创建文本提取器实例"""
    return TextExtractor()


@pytest.fixture
def sample_pdf_path():
    """示例 PDF 文件路径"""
    return Path(__file__).parent.parent / "fixtures" / "sample.pdf"


@pytest.fixture
def sample_docx_path():
    """示例 DOCX 文件路径"""
    return Path(__file__).parent.parent / "fixtures" / "sample.docx"


class TestFileType:
    """文件类型测试"""

    def test_file_type_values(self):
        """测试文件类型值"""
        assert FileType.PDF.value == "pdf"
        assert FileType.DOCX.value == "docx"
        assert FileType.JSON.value == "json"
        assert FileType.IMAGE.value == "image"


class TestExtractionStatus:
    """提取状态测试"""

    def test_status_values(self):
        """测试状态值"""
        assert ExtractionStatus.SUCCESS.value == "success"
        assert ExtractionStatus.FAILED.value == "failed"
        assert ExtractionStatus.PARTIAL.value == "partial"


class TestExtractedDocument:
    """ExtractedDocument 测试"""

    def test_create_document(self):
        """测试创建文档"""
        doc = ExtractedDocument(
            raw_text="测试文本",
            page_texts=["测试文本"],
            metadata={"file_name": "test.pdf"},
        )

        assert doc.raw_text == "测试文本"
        assert len(doc.page_texts) == 1
        assert doc.status == ExtractionStatus.SUCCESS
        assert doc.warnings == []
        assert doc.duration_ms is None

    def test_document_defaults(self):
        """测试文档默认值"""
        doc = ExtractedDocument(raw_text="test")
        assert doc.page_texts == []
        assert doc.metadata == {}
        assert doc.warnings == []


class TestTextExtractor:
    """TextExtractor 测试"""

    def test_detect_file_type_pdf(self, extractor):
        """测试 PDF 文件类型检测"""
        # PDF 文件头
        pdf_content = b"%PDF-1.4"
        file_type = extractor._detect_file_type("test.pdf", pdf_content)
        assert file_type == FileType.PDF

    def test_detect_file_type_docx(self, extractor):
        """测试 DOCX 文件类型检测"""
        # ZIP 文件头（DOCX 是 ZIP 格式）
        docx_content = b"PK\x03\x04"
        file_type = extractor._detect_file_type("test.docx", docx_content)
        assert file_type == FileType.DOCX

    def test_detect_file_type_json(self, extractor):
        """测试 JSON 文件类型检测"""
        json_content = b'{"name": "test"}'
        file_type = extractor._detect_file_type("test.json", json_content)
        assert file_type == FileType.JSON

    def test_detect_file_type_unsupported(self, extractor):
        """测试不支持的文件类型"""
        with pytest.raises(Exception):
            extractor._detect_file_type("test.txt", b"test")

    def test_detect_file_type_old_doc(self, extractor):
        """测试旧版 .doc 格式"""
        with pytest.raises(Exception) as exc_info:
            extractor._detect_file_type("test.doc", b"test")
        assert ".doc" in str(exc_info.value).lower()

    def test_extract_json(self, extractor):
        """测试 JSON 文件提取"""
        json_data = {
            "name": "张三",
            "phone": "13800138000",
            "education": [{"school": "北京大学", "degree": "本科"}],
        }
        json_content = json.dumps(json_data, ensure_ascii=False).encode("utf-8")

        result = extractor.extract(json_content, "test.json")

        assert result.status == ExtractionStatus.SUCCESS
        assert "张三" in result.raw_text
        assert "北京大学" in result.raw_text
        assert result.metadata["file_type"] == "json"
        assert result.metadata["is_structured"] is True

    def test_extract_empty_file(self, extractor):
        """测试空文件"""
        with pytest.raises(Exception) as exc_info:
            extractor.extract(b"", "test.pdf")
        assert "空" in str(exc_info.value) or "0 字节" in str(exc_info.value)

    def test_extract_large_file(self, extractor):
        """测试超大文件"""
        # 创建超过 50MB 的文件
        large_content = b"x" * (51 * 1024 * 1024)

        with pytest.raises(Exception) as exc_info:
            extractor.extract(large_content, "large.pdf")
        assert "超过限制" in str(exc_info.value) or "大小" in str(exc_info.value)

    def test_clean_text(self, extractor):
        """测试文本清理"""
        # 测试跨页断行合并
        text = "这是一个测-\n试文本"
        cleaned = extractor._clean_text(text)
        assert "测试" in cleaned

        # 测试移除多余空白
        text = "  行1  \n\n\n  行2  "
        cleaned = extractor._clean_text(text)
        assert cleaned == "行1\n行2"

    def test_get_text_extractor(self):
        """测试获取全局实例"""
        extractor = get_text_extractor()
        assert isinstance(extractor, TextExtractor)
