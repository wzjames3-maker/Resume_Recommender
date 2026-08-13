import enum
import hashlib
import re


class PIIType(str, enum.Enum):
    phone = "phone"
    email = "email"
    id_card = "id_card"
    name = "name"
    address = "address"


class PIIRedactionError(Exception):
    pass


class PIIMatch:
    __slots__ = ("end", "pii_type", "start", "value")

    def __init__(self, pii_type: PIIType, value: str, start: int, end: int):
        self.pii_type = pii_type
        self.value = value
        self.start = start
        self.end = end


class PIIMappingEntry:
    __slots__ = ("content_hash", "pii_type", "token", "value")

    def __init__(self, pii_type: PIIType, value: str, token: str):
        self.pii_type = pii_type
        self.value = value
        self.token = token
        self.content_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()


_PHONE_RE = re.compile(r"(?<![\d+])(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
# A-15：提示词/标签式姓名（「姓名: 张三」「联系人: 李四」「Name: ...」）。姓名明文另落 candidates.name
# 供查重/展示（本地不出站），此处仅防止姓名随 IR 出站到外部模型。
# 中文标签允许省略冒号；英文 Name/Contact 必须为行首独立字段标签且带冒号，
# 避免「Name of the company is Acme」被误当姓名。
_NAME_RE = re.compile(r"(?m)^(?:姓名|名字|联系人|英文名)\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})")
_EN_NAME_RE = re.compile(
    r"(?m)^(?:英文名|Name|Contact)\s*[:：]\s*([A-Za-z][A-Za-z .]{1,48})",
    re.IGNORECASE,
)
_ADDRESS_LABEL_RE = re.compile(
    r"(?m)^(?:现住址|通讯地址|住址|地址|Address)(?=\s|[:：]|$)\s*[:：]?\s*([^\n]{4,120})",
    re.IGNORECASE,
)
# 标签式地址单行值可能同行尾随其他字段（如「文三路 90 号 电话 13800000000」），
# 在常见字段标签处截断，避免整行结构化校验失败导致地址漏识别。
_FIELD_LABEL_TAIL_RE = re.compile(
    r"\s+(?:电话|手机|邮箱|Email|姓名|名字|技能|工作|教育|毕业|学校|籍贯|政治面貌|"
    r"期望|求职意向|薪资|民族|婚姻|性别|出生|年龄|身份证)\s*[:：]?\s*\S"
)
_STRUCTURED_ADDRESS_RE = re.compile(
    r"(?m)^(?:(?:安徽|福建|甘肃|广东|贵州|海南|河北|黑龙江|河南|湖北|湖南|江苏|江西|吉林|辽宁|青海|"
    r"陕西|山东|山西|四川|台湾|云南|浙江)省)?[\u4e00-\u9fa5]{2,4}市"
    r"[\u4e00-\u9fa5]{2,8}(?:区|县)"
    r"(?:[\u4e00-\u9fa5]{1,20}(?:路|街|巷)(?:\s*\d+\s*(?:号|弄|栋|楼|室|座|单元)?)*|"
    r"[\u4e00-\u9fa5]{1,20}(?:苑|小区))$"
)


def identify_pii(text: str) -> list[PIIMatch]:
    spans: list[PIIMatch] = []
    for matcher, pii_type in (
        (_PHONE_RE, PIIType.phone),
        (_EMAIL_RE, PIIType.email),
        (_ID_CARD_RE, PIIType.id_card),
    ):
        for m in matcher.finditer(text):
            spans.append(PIIMatch(pii_type, m.group(0), m.start(), m.end()))
    for m in _NAME_RE.finditer(text):
        spans.append(PIIMatch(PIIType.name, m.group(1), m.start(1), m.end(1)))
    for m in _EN_NAME_RE.finditer(text):
        spans.append(PIIMatch(PIIType.name, m.group(1), m.start(1), m.end(1)))
    for match in _ADDRESS_LABEL_RE.finditer(text):
        raw = match.group(1)
        value = _truncate_at_field_label(raw.strip())
        if _is_address_candidate(value):
            start = match.start(1) + len(raw) - len(raw.lstrip())
            spans.append(PIIMatch(PIIType.address, value, start, start + len(value)))
    for match in _STRUCTURED_ADDRESS_RE.finditer(text):
        value = match.group(0).strip()
        if _is_address_candidate(value):
            start = match.start() + len(match.group(0)) - len(match.group(0).lstrip())
            spans.append(PIIMatch(PIIType.address, value, start, start + len(value)))
    return _resolve_overlaps(text, spans)


def _truncate_at_field_label(value: str) -> str:
    """标签式地址值同行尾随其他字段时，在常见字段标签处截断。

    如「现住址：浙江省杭州市西湖区文三路 90 号 电话 13800000000」，
    截断为「浙江省杭州市西湖区文三路 90 号」后再走地址候选校验，
    避免尾随字段使整行结构化 fullmatch 失败导致地址漏识别。
    """
    m = _FIELD_LABEL_TAIL_RE.search(value)
    if m:
        return value[: m.start()]
    return value


def _is_address_candidate(value: str) -> bool:
    return _STRUCTURED_ADDRESS_RE.fullmatch(value.strip()) is not None


def _resolve_overlaps(text: str, spans: list[PIIMatch]) -> list[PIIMatch]:
    """重叠 span 合并为覆盖区间（防止丢弃 span 造成 PII 局部泄漏）。

    类型取非 name 优先（name 为宽松提示词匹配，phone/email/id_card 更精确）。
    """
    if not spans:
        return []
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    merged: list[PIIMatch] = [spans[0]]
    for span in spans[1:]:
        last = merged[-1]
        if span.start <= last.end:
            end = max(last.end, span.end)
            pii_type = last.pii_type if last.pii_type != PIIType.name else span.pii_type
            merged[-1] = PIIMatch(pii_type, text[last.start:end], last.start, end)
        else:
            merged.append(span)
    return merged


def _mask_with_token(text: str, spans: list[PIIMatch]) -> tuple[str, list[PIIMappingEntry]]:
    mapping: list[PIIMappingEntry] = []
    parts: list[str] = []
    cursor = 0
    for i, span in enumerate(spans):
        parts.append(text[cursor:span.start])
        token = f"PII:{span.pii_type.value}:{i}"
        mapping.append(PIIMappingEntry(span.pii_type, span.value, token))
        parts.append(token)
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts), mapping


def desensitize_text(text: str) -> tuple[str, list[PIIMappingEntry]]:
    """外发前调用。识别 + 脱敏任一失败即 fail-closed。"""
    try:
        text.encode("utf-8")  # 孤立代理对等无法安全序列化 → fail-closed
        spans = identify_pii(text)
        masked, mapping = _mask_with_token(text, spans)
        # 校验：明文值不得残留在输出中（fail-closed）
        for entry in mapping:
            if entry.value and entry.value in masked:
                raise PIIRedactionError(f"脱敏失败：明文残留 {entry.value}")
        return masked, mapping
    except (PIIRedactionError, UnicodeEncodeError, ValueError) as exc:
        raise PIIRedactionError(f"PII 脱敏失败，fail-closed: {exc}") from exc


def restore_pii_values(obj, mapping: list[PIIMappingEntry]):
    """LLM 输出中的 PII token 还原为明文（入库前调用，C-1 数据流闭环）。

    递归处理 dict/list/str；token 以整值替换与子串替换两种方式还原。
    """
    token_map = {entry.token: entry.value for entry in mapping}
    if not token_map:
        return obj

    def _restore(value):
        if isinstance(value, str):
            for token, plain in token_map.items():
                if token in value:
                    value = value.replace(token, plain)
            return value
        if isinstance(value, list):
            return [_restore(v) for v in value]
        if isinstance(value, dict):
            return {k: _restore(v) for k, v in value.items()}
        return value

    return _restore(obj)
