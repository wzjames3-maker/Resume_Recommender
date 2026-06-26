"""
智能招聘 RAG 推荐系统 - Milvus 连接管理

支持双模式：
- Standalone 模式：连接 docker-compose 中的 Milvus（开发/生产环境）
- Lite 模式：使用 pymilvus 的 Milvus Lite（本地单测 / CI 环境）
"""

from typing import Optional

from pymilvus import connections, utility

from src.common.config import get_settings
from src.common.logger import get_logger

logger = get_logger("milvus")


class MilvusConnection:
    """Milvus 连接管理器"""

    _instance: Optional["MilvusConnection"] = None
    _connected: bool = False
    _mode: Optional[str] = None  # "standalone" 或 "lite"

    def __new__(cls) -> "MilvusConnection":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self, mode: Optional[str] = None) -> None:
        """
        建立 Milvus 连接

        Args:
            mode: 连接模式（"standalone" 或 "lite"），默认从配置读取
        """
        if self._connected:
            return

        settings = get_settings()
        milvus_uri = settings.milvus.MILVUS_URI

        # 自动检测模式
        if mode is None:
            if milvus_uri and milvus_uri.startswith("http"):
                mode = "standalone"
            else:
                mode = "lite"

        self._mode = mode

        try:
            if mode == "standalone":
                # Standalone 模式：连接 Milvus Server
                logger.info(f"正在连接 Milvus Standalone: {milvus_uri}")
                connections.connect(
                    alias="default",
                    uri=milvus_uri,
                    token=settings.milvus.MILVUS_TOKEN or "",
                )
            else:
                # Lite 模式：使用 Milvus Lite（嵌入式）
                logger.info("正在使用 Milvus Lite 模式")
                import tempfile
                import os
                # 使用临时目录下的 .db 文件
                db_path = os.path.join(tempfile.gettempdir(), "milvus_lite.db")
                connections.connect(alias="default", uri=db_path)

            self._connected = True
            logger.info(f"Milvus 连接成功，模式: {mode}")

        except Exception as e:
            logger.error(f"Milvus 连接失败: {str(e)}")
            self._connected = False
            raise

    def disconnect(self) -> None:
        """关闭 Milvus 连接"""
        if self._connected:
            connections.disconnect(alias="default")
            self._connected = False
            self._mode = None
            logger.info("Milvus 连接已关闭")

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected

    def get_mode(self) -> Optional[str]:
        """获取连接模式"""
        return self._mode

    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            bool: 连接是否正常
        """
        try:
            if not self._connected:
                return False

            # 尝试获取 Collection 列表
            utility.list_collections()
            return True

        except Exception as e:
            logger.error(f"Milvus 健康检查失败: {str(e)}")
            return False


# 全局连接实例
milvus_connection = MilvusConnection()


def get_milvus_connection() -> MilvusConnection:
    """获取 Milvus 连接实例"""
    return milvus_connection
