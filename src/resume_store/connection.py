"""
智能招聘 RAG 推荐系统 - MongoDB 连接管理

使用 pymongo 实现 MongoDB 连接管理
"""

from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection

from src.common.config import get_settings
from src.common.logger import get_logger

logger = get_logger("mongodb")


class MongoDBConnection:
    """MongoDB 连接管理器"""

    _instance: Optional["MongoDBConnection"] = None
    _client: Optional[MongoClient] = None
    _database: Optional[Database] = None

    def __new__(cls) -> "MongoDBConnection":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> None:
        """建立 MongoDB 连接"""
        if self._client is not None:
            return

        settings = get_settings()
        mongodb_url = settings.mongodb.MONGODB_URL

        logger.info(f"正在连接 MongoDB: {mongodb_url}")

        try:
            self._client = MongoClient(
                mongodb_url,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
            )

            # 测试连接
            self._client.admin.command("ping")

            # 获取数据库
            self._database = self._client[settings.mongodb.MONGODB_DATABASE]

            logger.info(f"MongoDB 连接成功，数据库: {settings.mongodb.MONGODB_DATABASE}")

        except Exception as e:
            logger.error(f"MongoDB 连接失败: {str(e)}")
            self._client = None
            self._database = None
            raise

    def disconnect(self) -> None:
        """关闭 MongoDB 连接"""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._database = None
            logger.info("MongoDB 连接已关闭")

    def get_database(self) -> Database:
        """获取数据库实例"""
        if self._database is None:
            self.connect()
        return self._database

    def get_collection(self, collection_name: str) -> Collection:
        """获取集合实例"""
        database = self.get_database()
        return database[collection_name]

    def health_check(self) -> bool:
        """健康检查"""
        try:
            if self._client is None:
                return False
            self._client.admin.command("ping")
            return True
        except Exception as e:
            logger.error(f"MongoDB 健康检查失败: {str(e)}")
            return False


# 全局连接实例
mongodb_connection = MongoDBConnection()


def get_mongodb() -> MongoDBConnection:
    """获取 MongoDB 连接实例"""
    return mongodb_connection


def get_resume_collection() -> Collection:
    """获取简历集合"""
    return mongodb_connection.get_collection("resumes")
