import io
import os
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from xml.etree import ElementTree as ET

from app.services.resume.blocks import Block, BlockKind

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, source: str | bytes) -> list[Block]:
        ...


class _BlockCursor:
    def __init__(self):
        self._next = 0

    def next_id(self) -> int:
        self._next += 1
        return self._next


class DocxExtractor(BaseExtractor):
    """主力通道：python-docx 正文段落 + 全部表格 + 文本框 XML 遍历三通道。"""

    def extract(self, source: str | bytes) -> list[Block]:
        import docx

        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        doc = docx.Document(io.BytesIO(data))
        cursor = _BlockCursor()
        blocks: list[Block] = []

        # 通道 1：正文段落（含文本框字面量，按阅读顺序取自 body 中的 w:p）
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                blocks.append(Block(BlockKind.paragraph, text, cursor.next_id()))

        # 通道 2：全部表格——行主序展平，每行保留「单元格: 值」结构
        for table in doc.tables:
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append(Block(BlockKind.table, "\n".join(rows), cursor.next_id()))

        # 通道 3：文本框 XML 遍历（python-docx 不直接暴露文本框文本）
        for tb in _iter_textboxes(data):
            text = " ".join(tb.split())
            if text:
                blocks.append(Block(BlockKind.textbox, text, cursor.next_id()))

        return blocks


def _iter_textboxes(data: bytes) -> list[str]:
    """从 document.xml 中遍历所有 w:txbxContent 下的 w:t 文本。"""
    texts: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        return texts
    root = ET.fromstring(xml)
    for txbx in root.iter(W_NS + "txbxContent"):
        part = "".join(t.text or "" for t in txbx.iter(W_NS + "t"))
        if part.strip():
            texts.append(part.strip())
    return texts


class PdfExtractor(BaseExtractor):
    """pdf 文本层抽取（不做 OCR）。"""

    def extract(self, source: str | bytes) -> list[Block]:
        import pypdf

        stream = io.BytesIO(source if isinstance(source, bytes) else Path(source).read_bytes())
        reader = pypdf.PdfReader(stream)
        cursor = _BlockCursor()
        blocks = []
        for page in reader.pages:
            text = page.extract_text() or ""
            text = " ".join(text.split())
            if text:
                blocks.append(Block(BlockKind.paragraph, text, cursor.next_id()))
        return blocks


class TextExtractor(BaseExtractor):
    def extract(self, source: str | bytes) -> list[Block]:
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="ignore")
        else:
            with open(source, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        cursor = _BlockCursor()
        return [Block(BlockKind.paragraph, line.strip(), cursor.next_id())
                for line in text.splitlines() if line.strip()]


class LibreOfficeConverter:
    """兜底通道：soffice headless 转 docx 后重抽。资源受限（见 safety.resource_limits）。"""

    def convert(self, src_path: str, out_dir: str) -> str:
        import subprocess

        from app.services.resume.safety import resource_limits

        out_path = os.path.join(out_dir, os.path.basename(src_path).replace(".doc", ".docx"))
        cmd = ["soffice", "--headless", "--convert-to", "docx", "--outdir", out_dir, src_path]
        with resource_limits(cpu_seconds=60, mem_bytes=1024 * 1024 * 1024):
            result = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        if result.returncode != 0 or not os.path.exists(out_path):
            raise ValueError(f"LibreOffice 转换失败: {result.stderr.decode(errors='ignore')}")
        return out_path


def extract_resume(path: str, fmt: str) -> list[Block]:
    """按格式分派主力抽取；.doc 旧格式走 LibreOffice 兜底。"""
    if fmt == "docx":
        return DocxExtractor().extract(path)
    if fmt == "pdf":
        return PdfExtractor().extract(path)
    if fmt == "txt":
        return TextExtractor().extract(path)
    if fmt == "doc":
        converter = LibreOfficeConverter()
        converted = converter.convert(path, os.path.dirname(path))
        try:
            return DocxExtractor().extract(converted)
        finally:
            os.remove(converted)
    raise ValueError(f"不支持的简历格式: {fmt}")