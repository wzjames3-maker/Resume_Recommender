import re

RESUME_SCHEMA_VERSION = "resume/v1"

DEGREES = {"初中", "高中", "中专", "大专", "本科", "硕士", "博士"}
GENDERS = {"男", "女"}
WORK_TYPES = {"full_time", "intern", "part_time", "project"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PHONE_RE = re.compile(r"^\d{7,15}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

MAX_STR = 2000
MAX_ARRAY = 100

KNOWN_FIELDS = {
    "name", "gender", "birth_month", "phone", "email", "highest_degree",
    "hometown", "political_status", "expected_position", "city", "expected_city",
    "skills", "education", "work", "project",
}


class SchemaValidationError(Exception):
    pass


def _validate_common(record: dict) -> None:
    unknown = set(record) - KNOWN_FIELDS
    if unknown:
        raise SchemaValidationError(f"未知字段: {sorted(unknown)}")
    for k, v in record.items():
        if isinstance(v, str) and len(v) > MAX_STR:
            raise SchemaValidationError(f"字段 {k} 超长（>{MAX_STR}）")
    for k in ("name", "hometown", "political_status", "expected_position", "city", "expected_city"):
        if record.get(k) is not None and not isinstance(record[k], str):
            raise SchemaValidationError(f"字段 {k} 必须为字符串或 null")
    if record.get("gender") not in (None, "男", "女"):
        raise SchemaValidationError("gender 枚举非法")
    if record.get("highest_degree") is not None and record["highest_degree"] not in DEGREES:
        raise SchemaValidationError("highest_degree 枚举非法")
    for k in ("birth_month",):
        v = record.get(k)
        if v is not None and not MONTH_RE.match(v):
            raise SchemaValidationError(f"{k} 必须为 YYYY-MM")
    for k in ("city", "expected_city"):
        v = record.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > 128):
            raise SchemaValidationError(f"{k} 非法")
    if record.get("phone") is not None and not PHONE_RE.match(record["phone"]):
        raise SchemaValidationError("phone 格式非法")
    if record.get("email") is not None and not EMAIL_RE.match(record["email"]):
        raise SchemaValidationError("email 格式非法")


def _validate_dates(entry: dict, label: str) -> None:
    for k in ("start", "end"):
        v = entry.get(k)
        if v is not None and not MONTH_RE.match(v):
            raise SchemaValidationError(f"{label}.{k} 必须为 YYYY-MM 或 null")


def _validate_arrays(record: dict) -> None:
    for key, label in (("education", "education"), ("work", "work"), ("project", "project")):
        arr = record.get(key)
        if arr is None:
            continue
        if not isinstance(arr, list):
            raise SchemaValidationError(f"{key} 必须为数组")
        if len(arr) > MAX_ARRAY:
            raise SchemaValidationError(f"{key} 元素超过 {MAX_ARRAY}")
        for i, item in enumerate(arr):
            _validate_dates(item, f"{key}[{i}]")
        if key == "work":
            for i, item in enumerate(arr):
                if item.get("type") not in (None, "full_time", "intern", "part_time", "project"):
                    raise SchemaValidationError(f"work[{i}].type 枚举非法")
    if record.get("skills") is not None:
        if not isinstance(record["skills"], list) or len(record["skills"]) > MAX_ARRAY:
            raise SchemaValidationError("skills 必须为数组且 ≤100 项")
        for s in record["skills"]:
            if not isinstance(s, str) or len(s) > 200:
                raise SchemaValidationError("skills 元素非法")


def validate_candidate_json(candidate: dict) -> None:
    if not isinstance(candidate, dict) or not candidate:
        raise SchemaValidationError("candidate 必须为非空对象")
    _validate_common(candidate)
    _validate_arrays(candidate)