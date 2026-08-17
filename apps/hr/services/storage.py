# coding=utf-8
"""
    @project: MaxKB
    @file： storage.py
    @date：2026/8/15
    @desc: 简历/附件对象存储抽象：LocalStorage（默认，本地文件系统）与 S3Storage（MinIO/S3 兼容）。
           通过 MAXKB_STORAGE_BACKEND=local|s3 选择；S3 参数走 MAXKB_S3_* 环境变量。
"""
import os
import shutil
import tempfile

from maxkb.const import PROJECT_DIR

LOCAL_STORAGE_ROOT = os.path.join(PROJECT_DIR, "data")


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
