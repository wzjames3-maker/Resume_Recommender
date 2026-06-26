"""测试登录限流（SEC-T08）"""
import pytest
import asyncio
from src.common.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_allows_within_limit(self):
        limiter = RateLimiter()
        for _ in range(10):
            assert asyncio.run(limiter.is_allowed("test:key", limit=10))

    def test_blocks_over_limit(self):
        limiter = RateLimiter()
        for _ in range(10):
            asyncio.run(limiter.is_allowed("test:block", limit=10))
        assert not asyncio.run(limiter.is_allowed("test:block", limit=10))

    def test_different_keys_independent(self):
        limiter = RateLimiter()
        for _ in range(10):
            asyncio.run(limiter.is_allowed("key:A", limit=10))
        assert asyncio.run(limiter.is_allowed("key:B", limit=10))
