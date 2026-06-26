"""
智能招聘 RAG 推荐系统 - OCR 提取模块

使用 DeepSeek-OCR API 进行图片文字识别
"""

import base64
import io
import time
from typing import List, Optional

import httpx
from PIL import Image, ImageEnhance, ImageFilter

from src.common.config import get_settings
from src.common.errors import ErrorCode, ExternalServiceError, ValidationError
from src.common.logger import get_logger
from src.resume_parser.text_extractor import ExtractedDocument, ExtractionStatus

logger = get_logger("ocr_extractor")

# 支持的图片格式
SUPPORTED_IMAGE_FORMATS = {"png", "jpg", "jpeg", "webp"}

# 默认配置
DEFAULT_TIMEOUT = 60  # 秒
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒


class OCRExtractor:
    """OCR 提取器"""

    def __init__(self):
        """初始化 OCR 提取器"""
        self.settings = get_settings()
        self.api_key = self.settings.llm.LLM_API_KEY
        self.api_base_url = "https://api.deepseek.com/v1"
        self.timeout = DEFAULT_TIMEOUT

    def extract(
        self,
        image_content: bytes,
        file_name: str,
        file_format: Optional[str] = None,
    ) -> ExtractedDocument:
        """
        从图片中提取文字

        Args:
            image_content: 图片内容（二进制）
            file_name: 文件名
            file_format: 图片格式（可选，自动检测）

        Returns:
            ExtractedDocument: 提取的文档结构

        Raises:
            ValidationError: 格式错误、处理失败等
        """
        start_time = time.time()

        # 检查文件大小
        if len(image_content) == 0:
            raise ValidationError(
                error_code=ErrorCode.SYS_001,
                detail="图片文件为空（0 字节）",
            )

        # 自动检测格式
        if file_format is None:
            file_format = self._detect_format(file_name)

        # 验证格式
        if file_format.lower() not in SUPPORTED_IMAGE_FORMATS:
            raise ValidationError(
                error_code=ErrorCode.RESUME_003,
                detail=f"不支持的图片格式: {file_format}，支持: {', '.join(SUPPORTED_IMAGE_FORMATS)}",
            )

        try:
            # 图片预处理
            processed_image = self._preprocess_image(image_content)

            # 调用 OCR API
            ocr_text = self._call_ocr_api(processed_image, file_format)

            # 后处理
            cleaned_text = self._postprocess_text(ocr_text)

            # 计算耗时
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"OCR 提取完成: {file_name}, 耗时: {duration_ms}ms, "
                f"文本长度: {len(cleaned_text)}"
            )

            return ExtractedDocument(
                raw_text=cleaned_text,
                page_texts=[cleaned_text],
                metadata={
                    "file_name": file_name,
                    "file_type": "image",
                    "file_format": file_format,
                    "file_size": len(image_content),
                    "extraction_tool": "deepseek-ocr",
                },
                status=ExtractionStatus.SUCCESS,
                duration_ms=duration_ms,
            )

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"OCR 提取失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.RESUME_002,
                detail=f"OCR 提取失败: {str(e)}",
            )

    def _detect_format(self, file_name: str) -> str:
        """
        检测图片格式

        Args:
            file_name: 文件名

        Returns:
            str: 图片格式
        """
        from pathlib import Path

        suffix = Path(file_name).suffix.lower().lstrip(".")

        # 先处理 jpeg -> jpg 映射
        if suffix == "jpeg":
            return "jpg"

        if suffix in SUPPORTED_IMAGE_FORMATS:
            return suffix

        raise ValidationError(
            error_code=ErrorCode.RESUME_003,
            detail=f"无法识别的图片格式: {file_name}",
        )

    def _preprocess_image(self, image_content: bytes) -> bytes:
        """
        图片预处理：自动旋转校正、对比度增强、降噪

        Args:
            image_content: 原始图片内容

        Returns:
            bytes: 处理后的图片内容
        """
        try:
            # 打开图片
            img = Image.open(io.BytesIO(image_content))

            # 自动旋转校正（基于 EXIF 信息）
            from PIL import ImageOps

            img = ImageOps.exif_transpose(img)

            # 转换为 RGB（如果是 RGBA）
            if img.mode == "RGBA":
                img = img.convert("RGB")

            # 对比度增强
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.2)

            # 锐度增强
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.1)

            # 降噪（轻微模糊）
            img = img.filter(ImageFilter.MedianFilter(size=3))

            # 转回 bytes
            output = io.BytesIO()
            img.save(output, format="PNG", quality=95)
            return output.getvalue()

        except Exception as e:
            logger.warning(f"图片预处理失败，使用原始图片: {str(e)}")
            return image_content

    def _call_ocr_api(
        self, image_content: bytes, file_format: str
    ) -> str:
        """
        调用 DeepSeek-OCR API

        Args:
            image_content: 图片内容
            file_format: 图片格式

        Returns:
            str: OCR 识别结果
        """
        # 编码图片为 base64
        image_base64 = base64.b64encode(image_content).decode("utf-8")

        # 构建请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请识别这张图片中的所有文字内容，保持原始格式和结构。只返回识别的文字，不要添加任何解释。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{file_format};base64,{image_base64}",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 4096,
        }

        # 带重试的 API 调用
        for attempt in range(MAX_RETRIES):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        f"{self.api_base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                    # 检查响应
                    if response.status_code != 200:
                        error_msg = f"API 返回错误: {response.status_code}"
                        logger.warning(error_msg)

                        if attempt < MAX_RETRIES - 1:
                            time.sleep(RETRY_DELAY * (2**attempt))
                            continue
                        else:
                            raise ExternalServiceError(
                                error_code=ErrorCode.SYS_005,
                                detail=error_msg,
                            )

                    # 解析响应
                    result = response.json()
                    ocr_text = result["choices"][0]["message"]["content"]

                    return ocr_text

            except httpx.TimeoutException:
                logger.warning(f"API 超时，重试 {attempt + 1}/{MAX_RETRIES}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (2**attempt))
                else:
                    raise ExternalServiceError(
                        error_code=ErrorCode.SYS_004,
                        detail="OCR API 调用超时",
                    )

            except Exception as e:
                if isinstance(e, ExternalServiceError):
                    raise
                logger.error(f"API 调用异常: {str(e)}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (2**attempt))
                else:
                    raise ExternalServiceError(
                        error_code=ErrorCode.SYS_005,
                        detail=f"OCR API 调用失败: {str(e)}",
                    )

        # 不应到达这里
        raise ExternalServiceError(
            error_code=ErrorCode.SYS_005,
            detail="OCR API 调用失败",
        )

    def _postprocess_text(self, text: str) -> str:
        """
        OCR 结果后处理

        Args:
            text: 原始 OCR 文本

        Returns:
            str: 处理后的文本
        """
        # 合并断行
        text = text.replace("-\n", "")

        # 修正常见 OCR 错误
        # 0/O 混淆（在数字上下文中）
        import re

        # 电话号码中的 O 替换为 0
        text = re.sub(r"(1[3-9]\d)O(\d{4})", r"\g<1>0\g<2>", text)

        # 移除多余的空白行
        lines = text.split("\n")
        cleaned_lines = []
        prev_empty = False
        for line in lines:
            line = line.strip()
            if not line:
                if not prev_empty:
                    cleaned_lines.append("")
                    prev_empty = True
            else:
                cleaned_lines.append(line)
                prev_empty = False

        return "\n".join(cleaned_lines).strip()


# 全局 OCR 提取器实例
ocr_extractor = OCRExtractor()


def get_ocr_extractor() -> OCRExtractor:
    """获取 OCR 提取器实例"""
    return ocr_extractor
