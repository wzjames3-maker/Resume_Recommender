# coding=utf-8
"""
    @project: MaxKB
    @file： tests.py
    @date：2026/8/16
    @desc：内核 P1 修复回归测试（K1：Fork SSRF 加固）。
"""
from django.test import SimpleTestCase

from common.utils.fork import _SafeSession, _is_private_hostname


class ForkPrivateAddressTests(SimpleTestCase):
    """K1：SSRF 黑名单判定。"""

    def test_private_and_metadata_blocked(self):
        for url in (
            "http://127.0.0.1:8080/admin/api/knowledge",
            "http://10.0.0.5/",
            "http://172.16.0.1/",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]:8080/",
            "http://0.0.0.0/",
        ):
            self.assertTrue(_is_private_hostname(url), f"should block: {url}")

    def test_public_allowed(self):
        # 测试环境无外网 DNS：mock 解析结果为公网 IP
        import socket
        from unittest.mock import patch

        fake_infos = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:4860:4860::8888", 0, 0, 0)),
        ]
        with patch("common.utils.fork.socket.getaddrinfo", return_value=fake_infos):
            self.assertFalse(_is_private_hostname("http://example.com/"))
            self.assertFalse(_is_private_hostname("https://www.baidu.com/"))

    def test_unresolvable_blocked(self):
        self.assertTrue(_is_private_hostname("http://no-such-host-xyz-12345.invalid/"))

    def test_safe_session_blocks_before_connect(self):
        """对私网地址的请求必须在真正发起连接前被拒绝（无需网络）。"""
        session = _SafeSession()
        with self.assertRaises(ValueError):
            session.get("http://127.0.0.1:1/")

class SmartSplitPunctuationTests(SimpleTestCase):
    """P2-6：smart_split_paragraph 切点字符表修正——半角 !? 必须参与切分（此前全角写重）。"""

    def test_half_width_punctuation_splits(self):
        from common.utils.split_model import smart_split_paragraph

        text = "AAAA!BBBB?CCCC.DDDD"
        parts = smart_split_paragraph(text, limit=6)
        # 修复前：无切点 → 硬切为 ["AAAA!B","BBB?CC","CC.DD","DD"]；修复后按半角标点切
        self.assertEqual(len(parts), 4)
        self.assertTrue(all(p[-1] in "!?." for p in parts[:-1]))

    def test_full_width_punctuation_still_splits(self):
        from common.utils.split_model import smart_split_paragraph

        text = "第一段内容！第二段内容？第三段内容。第四段内容"
        parts = smart_split_paragraph(text, limit=6)
        self.assertGreaterEqual(len(parts), 3)


class ZipBombGuardTests(SimpleTestCase):
    """P2-5：zip 解压炸弹防护——总量/单文件上限。"""

    @staticmethod
    def _make_zip(content=b"hello world"):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a.txt", content)
        return io.BytesIO(buf.getvalue())

    def test_normal_zip_passes(self):
        import zipfile

        from common.handle.impl.text.zip_split_handle import validate_zip_sizes

        validate_zip_sizes(zipfile.ZipFile(self._make_zip()))  # 不抛

    def test_total_cap_enforced(self):
        import zipfile
        from unittest.mock import patch

        from common.handle.impl.text import zip_split_handle

        with patch("common.handle.impl.text.zip_split_handle._MAX_ZIP_TOTAL_UNCOMPRESSED", 1):
            with self.assertRaises(ValueError):
                zip_split_handle.validate_zip_sizes(zipfile.ZipFile(self._make_zip(b"x" * 100)))

    def test_file_cap_enforced(self):
        import zipfile
        from unittest.mock import patch

        from common.handle.impl.text import zip_split_handle

        with patch("common.handle.impl.text.zip_split_handle._MAX_ZIP_FILE_SIZE", 1):
            with self.assertRaises(ValueError):
                zip_split_handle.validate_zip_sizes(zipfile.ZipFile(self._make_zip(b"x" * 100)))


class PILPixelLimitTests(SimpleTestCase):
    """P2-4：PIL 像素上限有限值（原 None 无上限，解压炸弹可 OOM）。"""

    def test_pixel_limit_finite(self):
        from PIL import Image as PILImage

        import common.handle.impl.common_handle  # noqa: F401  模块导入即应用上限

        self.assertIsNotNone(PILImage.MAX_IMAGE_PIXELS)
        self.assertLessEqual(PILImage.MAX_IMAGE_PIXELS, 50_000_000)

