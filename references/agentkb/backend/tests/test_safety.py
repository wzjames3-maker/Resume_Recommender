import io
import zipfile

import pytest

from app.services.resume.safety import (
    MAX_EMBEDDED_OBJECTS,
    MAX_UNCOMPRESSED_SIZE,
    MAX_XML_DEPTH,
    resource_limits,
    validate_docx_zip,
    validate_pdf,
)


def _make_docx(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_macro_docx_rejected():
    data = _make_docx({
        "word/document.xml": "<w:document/>",
        "word/vbaProject.bin": b"MACRO",
    })
    with pytest.raises(ValueError, match="宏"):
        validate_docx_zip(io.BytesIO(data))


def test_encrypted_docx_rejected():
    data = _make_docx({
        "word/document.xml": "<w:document/>",
        "word/encryption.xml": "<enc/>",
    })
    with pytest.raises(ValueError, match="加密"):
        validate_docx_zip(io.BytesIO(data))


def test_zip_bomb_uncompressed_limit():
    # 压缩比极高：4MB 同字符压缩到很小，但解压后超过限制
    bomb = b"a" * (MAX_UNCOMPRESSED_SIZE + 1024)
    data = _make_docx({"word/document.xml": bomb})
    with pytest.raises(ValueError, match="解压后大小"):
        validate_docx_zip(io.BytesIO(data))


def test_deep_xml_rejected():
    depth = MAX_XML_DEPTH + 5
    nested = "<a>" * depth + "x" + "</a>" * depth
    data = _make_docx({"word/document.xml": nested})
    with pytest.raises(ValueError, match="XML 深度"):
        validate_docx_zip(io.BytesIO(data))


def test_too_many_embedded_objects_rejected():
    files = {"word/document.xml": "<w:document/>"}
    for i in range(MAX_EMBEDDED_OBJECTS + 1):
        files[f"word/embeddings/oleObject{i}.bin"] = b"obj"
        files[f"word/embeddings/package{i}.bin"] = b"bin"
    data = _make_docx(files)
    with pytest.raises(ValueError, match="嵌入对象"):
        validate_docx_zip(io.BytesIO(data))


def test_encrypted_pdf_rejected(tmp_path):
    import pypdf
    p = tmp_path / "enc.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret")
    with open(p, "wb") as f:
        writer.write(f)
    with pytest.raises(ValueError, match="加密"):
        validate_pdf(str(p))


def test_clean_mean_docx_accepted():
    data = _make_docx({"word/document.xml": "<w:document><w:body/></w:document>"})
    validate_docx_zip(io.BytesIO(data))  # 不抛异常


def test_resource_limits_restores_previous_limits():
    import resource as res
    before_cpu = res.getrlimit(res.RLIMIT_CPU)
    before_as = res.getrlimit(res.RLIMIT_AS)
    with resource_limits(cpu_seconds=1, mem_bytes=64 * 1024 * 1024):
        assert res.getrlimit(res.RLIMIT_CPU)[0] == 1
    # 退出后必须还原，否则会杀死后续测试进程（RLIMIT_CPU 为累计值）
    assert res.getrlimit(res.RLIMIT_CPU) == before_cpu
    assert res.getrlimit(res.RLIMIT_AS) == before_as


def test_check_file_signature():
    from app.services.resume.safety import check_file_signature
    check_file_signature(b"PK\x03\x04data", "docx")          # zip 魔数
    check_file_signature(b"%PDF-1.4", "pdf")
    check_file_signature(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "doc")  # OLE2
    check_file_signature(b"plain text", "txt")
    with pytest.raises(ValueError, match="签名"):
        check_file_signature(b"%PDF-1.4", "docx")
    with pytest.raises(ValueError, match="签名"):
        check_file_signature(b"\x00\x01\x02", "txt")          # 文本含 NUL