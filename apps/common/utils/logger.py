from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
import os
import logging
import re

maxkb_logger = logging.getLogger('max_kb')

# PII 脱敏正则（P2-4）：邮箱 / 中国大陆手机号（支持 +86 前缀及分隔符）/ 国际号码（须以 + 开头）
_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')
_MOBILE_RE = re.compile(r'(?<!\d)(?:\+?86[-\s]?)?(1[3-9]\d)[-\s]?(\d{4})[-\s]?(\d{4})(?!\d)')
_INTL_TEL_RE = re.compile(r'(?<![\d@.])\+\d{1,3}[- ](?:\d[- ]?){7,12}\d(?!\d)')


def desensitize(message: str) -> str:
    """掩码消息中的 PII：邮箱保留前 2 位，手机号保留前 3 后 4 位。"""
    if '@' in message:
        message = _EMAIL_RE.sub(
            lambda m: m.group(0)[:2] + '****' + m.group(0)[m.group(0).index('@'):], message)
    message = _INTL_TEL_RE.sub(lambda m: '+' + '*' * 6 + m.group(0)[-5:].replace(' ', ''), message)
    return _MOBILE_RE.sub(lambda m: f'{m.group(1)}****{m.group(3)}', message)


class PiiDesensitizeFilter(logging.Filter):
    """日志脱敏过滤器（P2-4）：对最终渲染后的日志消息做手机号/邮箱掩码。

    仅处理 record.getMessage() 结果；异常堆栈文本由 handler 渲染，不在本过滤器范围内。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            masked = desensitize(message)
        except Exception:  # noqa: BLE001 - 脱敏失败不能影响正常日志输出
            return True
        if masked != message:
            # 消息已完成插值，置空 args 避免二次格式化
            record.msg = masked
            record.args = None
        return True


class DailyTimedRotatingFileHandler(TimedRotatingFileHandler):
    def rotator(self, source, dest):
        """ Override the original method to rotate the log file daily."""
        dest = self._get_rotate_dest_filename(source)
        if os.path.exists(source) and not os.path.exists(dest):
            # 存在多个服务进程时, 保证只有一个进程成功 rotate
            os.rename(source, dest)

    @staticmethod
    def _get_rotate_dest_filename(source):
        date_yesterday = (
            datetime.now() - timedelta(days=1)
        ).strftime('%Y-%m-%d')
        path = [
            os.path.dirname(source),
            date_yesterday,
            os.path.basename(source)
        ]
        filename = os.path.join(*path)
        os.makedirs(os.path.dirname(filename), 0o700, exist_ok=True)
        return filename
