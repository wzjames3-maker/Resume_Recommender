import ipaddress
import socket
from urllib.parse import urlparse

import httpx

ALLOWED_PORTS = {443}
BLOCKED_IP_RANGES = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10MB

def _is_blocked(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    return any(ip in net for net in BLOCKED_IP_RANGES) or not ip.is_global

async def validate_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("仅允许 HTTPS")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("端口号必须为数字")
    if port and port not in ALLOWED_PORTS:
        raise ValueError(f"端口不允许: {port}")
    host = parsed.hostname
    if host is None:
        raise ValueError("缺少主机名")
    # 拒绝跨域重定向：连接测试与生产调用均禁用 allow_redirects
    # DNS 解析后再次校验 IP（防 DNS rebinding）
    for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        ip_text = info[4][0]
        if _is_blocked(ip_text):
            raise ValueError(f"目标地址被网关拒绝: {ip_text}")
    return True


async def http_post_json(url: str, headers: dict, payload: dict, timeout: float = 60.0) -> dict:
    """生产出站调用统一入口：SSRF 校验 + 禁重定向 + 响应大小限制。"""
    await validate_endpoint(url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload, follow_redirects=False)
        raw = resp.content
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError(f"响应超过 {MAX_RESPONSE_BYTES} 限制")
        resp.raise_for_status()
        return resp.json()