"""
智能招聘 RAG 推荐系统 - 日志模块

使用 python-json-logger 实现结构化 JSON 日志
"""

import logging
import sys
from typing import Optional

from pythonjsonlogger import jsonlogger

from src.common.config import get_settings


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """自定义 JSON 日志格式化器"""

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
        """添加自定义字段"""
        super().add_fields(log_record, record, message_dict)

        # 添加标准字段
        log_record["level"] = record.levelname
        log_record["module"] = record.module
        log_record["function"] = record.funcName
        log_record["line"] = record.lineno

        # 添加进程信息
        log_record["process_id"] = record.process
        log_record["thread_id"] = record.thread

        # 确保 timestamp 字段存在
        if "timestamp" not in log_record:
            log_record["timestamp"] = self.formatTime(record)


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    获取日志记录器

    Args:
        name: 日志记录器名称（通常是模块名）
        level: 日志级别（可选，默认从配置读取）

    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)

    # 如果已经配置过，直接返回
    if logger.handlers:
        return logger

    # 获取配置
    settings = get_settings()
    log_level = level or settings.app.LOG_LEVEL if hasattr(settings.app, "LOG_LEVEL") else "INFO"

    # 设置日志级别
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # 设置 JSON 格式化器
    formatter = CustomJsonFormatter(
        fmt="%(timestamp)s %(level)s %(name)s %(message)s",
        rename_fields={"timestamp": "@timestamp", "level": "severity"},
        datefmt="%Y-%m-%dT%H:%M:%S.%fZ",
    )
    console_handler.setFormatter(formatter)

    # 添加处理器
    logger.addHandler(console_handler)

    # 防止日志向上传播
    logger.propagate = False

    return logger


class LoggerMixin:
    """日志记录器混入类"""

    @property
    def logger(self) -> logging.Logger:
        """获取当前类的日志记录器"""
        return get_logger(self.__class__.__name__)


# 创建默认日志记录器
default_logger = get_logger("resume-rag")
