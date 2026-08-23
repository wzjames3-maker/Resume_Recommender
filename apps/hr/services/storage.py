# coding=utf-8
"""
    @project: MaxKB
    @file： storage.py
    @date：2026/8/15
    @desc: 简历/附件对象存储抽象：LocalStorage（默认，本地文件系统）与 S3Storage（MinIO/S3 兼容）。
           通过 MAXKB_STORAGE_BACKEND=local|s3 选择；S3 参数走 MAXKB_S3_* 环境变量。
"""
import logging
import os
import shutil
import tempfile

from common.exception.app_exception import AppApiException
from maxkb.const import PROJECT_DIR

LOCAL_STORAGE_ROOT = os.path.join(PROJECT_DIR, "data")

logger = logging.getLogger("hr")

# P3 加固：允许下载的存储 key 顶层目录（workspace 隔离前缀）
_DOWNLOADABLE_KEY_PREFIXES = ("resume", "offer")


def ensure_download_key_scoped(key, workspace_id):
    """P3 加固（纵深防御）：下载/读取前断言存储 key 归属当前 workspace。

    - 相对 key：必须形如 resume/{workspace_id}/... 或 offer/{workspace_id}/...，
      且经 os.path.normpath 归一后仍保持在该前缀下（防 "../" 路径穿越）；
    - 存量绝对路径记录（旧版 file_path 直接存本地绝对路径）：兼容放行，但归一后
      必须仍位于本地存储根目录或系统临时目录之内。
    校验失败记服务端日志并抛 AppApiException(404)，不向客户端泄露存储布局。
    """
    def _deny(reason):
        logger.warning("拦截越权存储访问 key=%r workspace=%s: %s", key, workspace_id, reason)
        raise AppApiException(404, "File not found")

    if not isinstance(key, str) or not key.strip():
        _deny("empty storage key")
    workspace_id = str(workspace_id)
    normalized = os.path.normpath(key.strip())
    if os.path.isabs(normalized):
        # 存量绝对路径：兼容放行，仅要求归一后仍在允许的根目录内
        path_abs = os.path.normpath(os.path.abspath(normalized))
        allowed_roots = (
            os.path.normpath(os.path.abspath(LOCAL_STORAGE_ROOT)),
            os.path.normpath(os.path.abspath(tempfile.gettempdir())),
        )
        if not any(path_abs == root or path_abs.startswith(root + os.sep) for root in allowed_roots):
            _deny("absolute path outside allowed roots")
        return
    parts = [part for part in normalized.replace("\\", "/").split("/") if part]
    if len(parts) < 3 or parts[0] not in _DOWNLOADABLE_KEY_PREFIXES or parts[1] != workspace_id:
        _deny("key not scoped to workspace")
    root_abs = os.path.normpath(os.path.abspath(LOCAL_STORAGE_ROOT))
    resolved_abs = os.path.normpath(os.path.abspath(os.path.join(root_abs, *parts)))
    if not resolved_abs.startswith(root_abs + os.sep):
        _deny("normalized path escapes storage root")


class StorageBackend:
    """对象存储后端接口：key 为相对路径（含 workspace 前缀），操作幂等。"""

    def save(self, key, source_path):
        raise NotImplementedError

    def exists(self, key):
        raise NotImplementedError

    def open(self, key):
        """返回本地文件路径（S3 后端会物化到临时文件）。"""
        raise NotImplementedError

    def delete(self, key):
        raise NotImplementedError


class LocalStorage(StorageBackend):
    def __init__(self, root=LOCAL_STORAGE_ROOT):
        self.root = root

    def _path(self, key):
        # 兼容存量绝对路径记录（旧版 file_path 为 data/resume/... 绝对路径）
        if os.path.isabs(key):
            return key
        return os.path.join(self.root, key)

    def save(self, key, source_path):
        target = self._path(key)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source_path, target)
        return target

    def exists(self, key):
        return os.path.exists(self._path(key))

    def open(self, key):
        path = self._path(key)
        if not os.path.exists(path):
            raise FileNotFoundError(key)
        return path

    def delete(self, key):
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)


class S3Storage(StorageBackend):
    def __init__(self, endpoint, access_key, secret_key, bucket, secure=False):
        from minio import Minio
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def save(self, key, source_path):
        self.client.fput_object(self.bucket, key, source_path)
        return key

    def exists(self, key):
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except Exception:
            return False

    def open(self, key):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(key)[1])
        handle.close()
        self.client.fget_object(self.bucket, key, handle.name)
        return handle.name

    def delete(self, key):
        # Let the offboarding ledger persist failures and provide an operational retry path.
        try:
            self.client.remove_object(self.bucket, key)
        except Exception as exc:
            # Existing HR callers handle OSError; preserve that contract for non-offboarding paths.
            raise OSError(str(exc)) from exc


_storage_instance = None


def get_storage():
    """按 MAXKB_STORAGE_BACKEND 返回存储后端（进程内缓存）；默认本地文件系统。"""
    global _storage_instance
    if _storage_instance is None:
        backend = os.getenv("MAXKB_STORAGE_BACKEND", "local")
        if backend == "s3":
            _storage_instance = S3Storage(
                endpoint=os.getenv("MAXKB_S3_ENDPOINT", "127.0.0.1:9000"),
                access_key=os.getenv("MAXKB_S3_ACCESS_KEY", ""),
                secret_key=os.getenv("MAXKB_S3_SECRET_KEY", ""),
                bucket=os.getenv("MAXKB_S3_BUCKET", "maxkb"),
                secure=os.getenv("MAXKB_S3_SECURE", "false").lower() == "true",
            )
        else:
            _storage_instance = LocalStorage()
    return _storage_instance


def reset_storage_for_tests():
    global _storage_instance
    _storage_instance = None
