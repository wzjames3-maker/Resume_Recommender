"""
智能招聘 RAG 推荐系统 - OCR 提取模块测试
"""

import pytest

from src.resume_parser.ocr_extractor import (
    OCRExtractor,
    SUPPORTED_IMAGE_FORMATS,
    get_ocr_extractor,
)
from src.resume_parser.text_extractor import ExtractionStatus


@pytest.fixture
def extractor():
    """创建 OCR 提取器实例"""
    return OCRExtractor()


class TestOCRExtractor:
    """OCRExtractor 测试"""

    def test_supported_formats(self):
        """测试支持的图片格式"""
        assert "png" in SUPPORTED_IMAGE_FORMATS
        assert "jpg" in SUPPORTED_IMAGE_FORMATS
        assert "jpeg" in SUPPORTED_IMAGE_FORMATS
        assert "webp" in SUPPORTED_IMAGE_FORMATS

    def test_detect_format_png(self, extractor):
        """测试 PNG 格式检测"""
        assert extractor._detect_format("test.png") == "png"
        assert extractor._detect_format("test.PNG") == "png"

    def test_detect_format_jpg(self, extractor):
        """测试 JPG 格式检测"""
        assert extractor._detect_format("test.jpg") == "jpg"
        assert extractor._detect_format("test.jpeg") == "jpg"
        assert extractor._detect_format("test.JPG") == "jpg"

    def test_detect_format_webp(self, extractor):
        """测试 WebP 格式检测"""
        assert extractor._detect_format("test.webp") == "webp"

    def test_detect_format_unsupported(self, extractor):
        """测试不支持的格式"""
        with pytest.raises(Exception) as exc_info:
            extractor._detect_format("test.bmp")
        assert "无法识别" in str(exc_info.value) or "不支持" in str(exc_info.value)

    def test_extract_empty_image(self, extractor):
        """测试空图片"""
        with pytest.raises(Exception) as exc_info:
            extractor.extract(b"", "test.png")
        assert "空" in str(exc_info.value) or "0 字节" in str(exc_info.value)

    def test_postprocess_text(self, extractor):
        """测试文本后处理"""
        # 测试断行合并
        text = "这是一段测-\n试文本"
        result = extractor._postprocess_text(text)
        assert "测试" in result

        # 测试 0/O 修正
        text = "电话: 138O0138000"
        result = extractor._postprocess_text(text)
        assert "13800138000" in result

        # 测试多余空行移除
        text = "行1\n\n\n\n行2"
        result = extractor._postprocess_text(text)
        assert result == "行1\n\n行2"

    def test_get_ocr_extractor(self):
        """测试获取全局实例"""
        extractor = get_ocr_extractor()
        assert isinstance(extractor, OCRExtractor)


class TestOCRIntegration:
    """OCR 集成测试（需要实际 API 调用）"""

    @pytest.mark.skip(reason="需要实际 API 调用")
    def test_extract_from_image(self, extractor):
        """测试从图片提取文字（需要实际 API）"""
        # 这个测试需要实际的图片文件和 API Key
        # 在 CI 环境中跳过
        pass
