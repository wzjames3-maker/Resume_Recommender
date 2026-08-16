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
