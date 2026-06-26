"""登录限流模块（Redis 滑动窗口）"""
import time
from collections import defaultdict
from typing import Dict, Tuple


class RateLimiter:
    """简单的内存滑动窗口限流器（生产应使用 Redis）"""

    def __init__(self):
        self._windows: Dict[str, Dict[int, int]] = defaultdict(dict)

    async def is_allowed(self, key: str, limit: int = 10, window: int = 60) -> bool:
        """
        检查请求是否被允许。

        Args:
            key: 限流 key（如 ratelimit:login:{ip}）
            limit: 窗口内最大请求数
            window: 窗口时间（秒）

        Returns:
            bool: True = 允许，False = 超限
        """
        now = int(time.time())
        bucket = self._windows[key]
        # 清理过期桶
        expired = [t for t in bucket if now - t >= window]
        for t in expired:
            del bucket[t]
        # 统计当前窗口内请求数
        count = sum(bucket.values())
        if count >= limit:
            return False
        # 记录当前秒的请求
        bucket[now] = bucket.get(now, 0) + 1
        return True


# 全局限流器实例
_login_limiter = RateLimiter()
