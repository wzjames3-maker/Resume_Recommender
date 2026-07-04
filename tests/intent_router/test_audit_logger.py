"""
智能招聘 RAG 推荐系统 - Intent 审计日志测试
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.intent_router.audit_logger import (
    IntentAuditLog,
    IntentAuditLogger,
    get_intent_audit_logger,
)


@pytest.fixture
def audit_logger():
    """创建审计日志记录器实例"""
    logger = IntentAuditLogger()
    logger.clear_logs()
    return logger


@pytest.fixture
def sample_log_data():
    """示例日志数据"""
    return {
        "query": "帮我找Java工程师",
        "detected_intent": "recruitment.search",
        "confidence": 0.9,
        "slots": {"job_title": "Java工程师"},
        "handler": "SearchHandler",
        "response_type": "success",
        "latency_ms": 150,
    }


class TestIntentAuditLog:
    """IntentAuditLog 测试"""

    def test_create_log(self):
        """测试创建日志"""
        log = IntentAuditLog(
            log_id="test-001",
            query="帮我找Java工程师",
            query_hash="abc123",
            detected_intent="recruitment.search",
            confidence=0.9,
            handler="SearchHandler",
            response_type="success",
        )

        assert log.log_id == "test-001"
        assert log.query == "帮我找Java工程师"
        assert log.detected_intent == "recruitment.search"
        assert log.confidence == 0.9
        assert log.fallback_triggered is False

    def test_log_with_fallback(self):
        """测试带 Fallback 的日志"""
        log = IntentAuditLog(
            log_id="test-002",
            query="一些输入",
            query_hash="def456",
            detected_intent="fallback",
            confidence=0.3,
            handler="FallbackHandler",
            response_type="fallback",
            fallback_triggered=True,
            fallback_reason="置信度过低",
        )

        assert log.fallback_triggered is True
        assert log.fallback_reason == "置信度过低"


class TestIntentAuditLogger:
    """IntentAuditLogger 测试"""

    def test_log_intent(self, audit_logger, sample_log_data):
        """测试记录意图日志"""
        log = audit_logger.log(**sample_log_data)

        assert isinstance(log, IntentAuditLog)
        assert log.detected_intent == "recruitment.search"
        assert log.confidence == 0.9

    def test_log_with_pii_desensitization(self, audit_logger):
        """测试 PII 脱敏"""
        log = audit_logger.log(
            query="帮我找手机号13800138000的候选人",
            detected_intent="recruitment.search",
            confidence=0.9,
            slots={},
            handler="SearchHandler",
            response_type="success",
            latency_ms=100,
        )

        # 手机号应该被脱敏
        assert "13800138000" not in log.query
        assert "手机号" in log.query

    def test_log_with_email_desensitization(self, audit_logger):
        """测试邮箱脱敏"""
        log = audit_logger.log(
            query="帮我找邮箱zhangsan@example.com的候选人",
            detected_intent="recruitment.search",
            confidence=0.9,
            slots={},
            handler="SearchHandler",
            response_type="success",
            latency_ms=100,
        )

        # 邮箱应该被脱敏
        assert "zhangsan@example.com" not in log.query
        assert "邮箱" in log.query

    def test_get_logs_all(self, audit_logger, sample_log_data):
        """测试获取所有日志"""
        audit_logger.log(**sample_log_data)
        audit_logger.log(**sample_log_data)

        logs = audit_logger.get_logs()

        assert len(logs) == 2

    def test_get_logs_by_intent(self, audit_logger, sample_log_data):
        """测试按意图过滤日志"""
        audit_logger.log(**sample_log_data)

        # 不同意图的日志
        audit_logger.log(
            query="你好",
            detected_intent="chat",
            confidence=0.9,
            slots={},
            handler="ChatHandler",
            response_type="success",
            latency_ms=50,
        )

        # 按意图过滤
        search_logs = audit_logger.get_logs(intent="recruitment.search")
        chat_logs = audit_logger.get_logs(intent="chat")

        assert len(search_logs) == 1
        assert len(chat_logs) == 1

    def test_get_logs_fallback_only(self, audit_logger):
        """测试只获取 Fallback 日志"""
        # 正常日志
        audit_logger.log(
            query="帮我找Java工程师",
            detected_intent="recruitment.search",
            confidence=0.9,
            slots={},
            handler="SearchHandler",
            response_type="success",
            latency_ms=100,
            fallback_triggered=False,
        )

        # Fallback 日志
        audit_logger.log(
            query="一些输入",
            detected_intent="fallback",
            confidence=0.3,
            slots={},
            handler="FallbackHandler",
            response_type="fallback",
            latency_ms=50,
            fallback_triggered=True,
            fallback_reason="置信度过低",
        )

        # 只获取 Fallback 日志
        fallback_logs = audit_logger.get_logs(fallback_only=True)

        assert len(fallback_logs) == 1
        assert fallback_logs[0].fallback_triggered is True

    def test_get_logs_by_time_range(self, audit_logger, sample_log_data):
        """测试按时间范围过滤日志"""
        audit_logger.log(**sample_log_data)

        # 查询过去 1 小时的日志
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)

        logs = audit_logger.get_logs(
            start_time=one_hour_ago,
            end_time=now,
        )

        assert len(logs) >= 1

    def test_get_statistics(self, audit_logger):
        """测试获取统计信息"""
        # 添加一些日志
        for i in range(10):
            audit_logger.log(
                query=f"测试查询 {i}",
                detected_intent="recruitment.search" if i % 2 == 0 else "chat",
                confidence=0.9 if i < 8 else 0.3,
                slots={},
                handler="SearchHandler" if i % 2 == 0 else "ChatHandler",
                response_type="success" if i < 8 else "fallback",
                latency_ms=100 + i * 10,
                fallback_triggered=i >= 8,
            )

        stats = audit_logger.get_statistics()

        assert stats["total"] == 10
        assert stats["fallback_count"] == 2
        assert stats["fallback_rate"] == 0.2
        assert stats["avg_latency_ms"] > 0
        assert "recruitment.search" in stats["intent_distribution"]
        assert "chat" in stats["intent_distribution"]

    def test_clear_logs(self, audit_logger, sample_log_data):
        """测试清除日志"""
        audit_logger.log(**sample_log_data)

        assert len(audit_logger.get_logs()) == 1

        audit_logger.clear_logs()

        assert len(audit_logger.get_logs()) == 0

    def test_desensitize_query(self, audit_logger):
        """测试查询脱敏"""
        # 手机号
        result = audit_logger._desensitize_query("手机号13800138000")
        assert "13800138000" not in result

        # 邮箱
        result = audit_logger._desensitize_query("邮箱test@example.com")
        assert "test@example.com" not in result

        # 身份证
        result = audit_logger._desensitize_query("身份证110101199001011234")
        assert "110101199001011234" not in result

    def test_generate_hash(self, audit_logger):
        """测试生成哈希"""
        hash1 = audit_logger._generate_hash("测试文本")
        hash2 = audit_logger._generate_hash("测试文本")
        hash3 = audit_logger._generate_hash("其他文本")

        assert hash1 == hash2
        assert hash1 != hash3

    def test_get_intent_audit_logger(self):
        """测试获取全局实例"""
        logger = get_intent_audit_logger()
        assert isinstance(logger, IntentAuditLogger)
