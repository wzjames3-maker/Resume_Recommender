import io
import zipfile
from contextlib import contextmanager

MAX_UNCOMPRESSED_SIZE = 100 * 1024 * 1024  # 解压后 ≤100MB
MAX_XML_DEPTH = 100
MAX_EMBEDDED_OBJECTS = 20
MAX_DISK_BYTES = 500 * 1024 * 1024  # 临时磁盘 ≤500MB
MAX_CONVERT_OUTPUT = 50 * 1024 * 1024  # 转换输出 ≤50MB


def _iter_zip_members(zf: zipfile.ZipFile):
    total = 0
    for info in zf.infolist():
        total += info.file_size
        if total > MAX_UNCOMPRESSED_SIZE:
            raise ValueError(f"解压后大小超过 {MAX_UNCOMPRESSED_SIZE} 限制")
        yield info


def validate_docx_zip(data: bytes | io.BytesIO) -> None:
    try:
        zf = zipfile.ZipFile(data)
    except zipfile.BadZipFile as exc:
        raise ValueError("不是合法的 docx (zip) 文件") from exc

    names = set(zf.namelist())
    if "word/vbaProject.bin" in names or any(n.endswith("vbaProject.bin") for n in names):
        raise ValueError("检测到宏，默认拒收")
    if "word/encryption.xml" in names:
        raise ValueError("检测到加密，默认拒收")

    embedded = sum(1 for n in names if n.startswith("word/embeddings/"))
    if embedded > MAX_EMBEDDED_OBJECTS:
        raise ValueError(f"嵌入对象数超过 {MAX_EMBEDDED_OBJECTS} 限制")

    for info in _iter_zip_members(zf):
        if info.filename == "word/document.xml":
            content = zf.read(info)
            if _xml_depth(content) > MAX_XML_DEPTH:
                raise ValueError(f"XML 深度超过 {MAX_XML_DEPTH} 限制")


def _xml_depth(xml: bytes) -> int:
    depth = 0
    max_depth = 0
    i = 0
    n = len(xml)
    while i < n:
        if xml[i:i+1] == b"<":
            if xml[i+1:i+2] == b"/":
                depth -= 1
            elif xml[i+1:i+2] == b"!" or xml[i+1:i+2] == b"?":
                pass
            else:
                depth += 1
                max_depth = max(max_depth, depth)
            i = xml.find(b">", i)
        else:
            i += 1
    return max_depth


def validate_pdf(path: str) -> None:
    import pypdf
    try:
        reader = pypdf.PdfReader(path)
    except Exception as exc:
        raise ValueError("不是合法的 PDF 文件") from exc
    if reader.is_encrypted:
        raise ValueError("检测到加密，默认拒收")


@contextmanager
def resource_limits(cpu_seconds: int = 60, mem_bytes: int = 1024 * 1024 * 1024):
    """在当前进程设置 CPU 与内存软上限（仅 POSIX），退出时**必须还原**。

    RLIMIT_CPU 为进程累计 CPU 时间，不还原会杀死长驻 worker / 测试进程。
    """
    resource_module = None
    prev_cpu = prev_as = None
    try:
        import resource
        resource_module = resource
        prev_cpu = resource_module.getrlimit(resource_module.RLIMIT_CPU)
        prev_as = resource_module.getrlimit(resource_module.RLIMIT_AS)
        # 仅下调 soft limit；绝不能下调 hard limit，否则无特权进程无法恢复。
        cpu_hard = prev_cpu[1]
        as_hard = prev_as[1]
        cpu_soft = cpu_seconds if cpu_hard < 0 else min(cpu_seconds, cpu_hard)
        as_soft = mem_bytes if as_hard < 0 else min(mem_bytes, as_hard)
        resource_module.setrlimit(resource_module.RLIMIT_CPU, (cpu_soft, cpu_hard))
        resource_module.setrlimit(resource_module.RLIMIT_AS, (as_soft, as_hard))
    except (ImportError, ValueError, OSError):
        pass  # 非 POSIX / 无权限环境跳过
    try:
        yield
    finally:
        try:
            if resource_module is not None and prev_cpu is not None:
                resource_module.setrlimit(resource_module.RLIMIT_CPU, prev_cpu)
            if resource_module is not None and prev_as is not None:
                resource_module.setrlimit(resource_module.RLIMIT_AS, prev_as)
        except (ImportError, ValueError, OSError):
            pass


_SIGNATURES = {
    "docx": (b"PK\x03\x04",),
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),  # OLE2 复合文档
    "pdf": (b"%PDF",),
}


def check_file_signature(head: bytes, fmt: str) -> None:
    """扩展名与文件签名一致性校验（MVP §3.3 验收）。不匹配抛 ValueError。"""
    if fmt in _SIGNATURES:
        if not any(head.startswith(sig) for sig in _SIGNATURES[fmt]):
            raise ValueError(f"文件签名与扩展名 {fmt} 不匹配")
    elif fmt in ("txt", "csv", "json"):
        if b"\x00" in head:
            raise ValueError(f"文本文件 {fmt} 含二进制内容，签名不匹配")
    else:
        raise ValueError(f"不支持的简历格式: {fmt}")


def cleanup_tempdir(tempdir: str) -> None:
    import shutil
    shutil.rmtree(tempdir, ignore_errors=True)


class ParseSafetyError(Exception):
    """文件安全校验失败（加密/宏/压缩炸弹等），不可重试。"""