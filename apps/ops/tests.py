# coding=utf-8
"""
@project: MaxKB
@Author：交接接手
@file： tests.py
@date：2026/08/15
@desc：ops 工具包测试（当前覆盖 celery heartbeat 探针文件目录）
"""
import importlib
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

# 注意：不能用 "import ops.celery.heartbeat as heartbeat_module"——
# ops/celery/__init__.py 的 "from .heartbeat import *" 会让属性链绑定到 heartbeat 函数而非模块。
heartbeat_module = importlib.import_module("ops.celery.heartbeat")

DEFAULT_WORKER_TMP_DIR = "/opt/maxkb-app/tmp"


class HeartbeatProbeTests(SimpleTestCase):
    """worker 心跳/就绪/退出探针文件的行为与目录可配置性。"""

    def _sender(self, worker_name="worker1"):
        return SimpleNamespace(
            hostname="{}@127.0.0.1".format(worker_name),
            eventer=SimpleNamespace(hostname="{}@127.0.0.1".format(worker_name)),
        )

    def test_heartbeat_creates_probe_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(heartbeat_module, "WORKER_TMP_DIR", tmp):
                heartbeat_module.heartbeat(self._sender())
                self.assertTrue(os.path.exists(os.path.join(tmp, "worker_heartbeat_worker1")))

    def test_worker_ready_creates_probe_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(heartbeat_module, "WORKER_TMP_DIR", tmp):
                heartbeat_module.worker_ready(self._sender())
                self.assertTrue(os.path.exists(os.path.join(tmp, "worker_ready_worker1")))

    def test_worker_shutdown_removes_probe_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(heartbeat_module, "WORKER_TMP_DIR", tmp):
                heartbeat_module.heartbeat(self._sender())
                heartbeat_module.worker_ready(self._sender())
                heartbeat_module.worker_shutdown(self._sender())
                self.assertEqual(os.listdir(tmp), [])

    def test_env_var_overrides_default_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"MAXKB_WORKER_TMP": tmp}):
                importlib.reload(heartbeat_module)
                try:
                    self.assertEqual(heartbeat_module.WORKER_TMP_DIR, tmp)
                finally:
                    # 恢复模块默认值，避免影响测试进程内其他用例/信号注册
                    heartbeat_module.WORKER_TMP_DIR = DEFAULT_WORKER_TMP_DIR
