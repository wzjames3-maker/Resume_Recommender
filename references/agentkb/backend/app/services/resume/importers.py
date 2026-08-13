import csv
import hashlib
import io
import json
import os
import uuid

from app.services.resume.schema import KNOWN_FIELDS, validate_candidate_json

CSV_HEADERS = ["name", "gender", "birth_month", "phone", "email", "highest_degree",
               "city", "expected_city", "expected_position", "skills",
               "max_education_desc", "max_work_desc"]


class ResumeImportError(Exception):
    pass


MAX_RECORDS = 100  # 单批 ≤100 份（PRD F6 ①，与 multipart 上传口径一致）
MAX_FIELD_LEN = 2000  # 单字段 ≤2000（spec §3.2）


def row_hash(row: dict) -> str:
    canonical = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_json_envelope(body: dict) -> tuple[dict, list[dict], list[dict]]:
    if not isinstance(body.get("upload_id"), str) or not body["upload_id"]:
        raise ResumeImportError("upload_id 批次级必填")
    if body.get("schema_version") != "resume-import/v1":
        raise ResumeImportError("schema_version 必须为 resume-import/v1")
    if not isinstance(body.get("template_version"), str) or not body["template_version"]:
        raise ResumeImportError("template_version 批次级必填")
    if not body.get("source_channel"):
        raise ResumeImportError("source_channel 批次级必填")
    records = body.get("records")
    if not isinstance(records, list) or not records:
        raise ResumeImportError("records 必须为非空数组")
    if len(records) > MAX_RECORDS:
        raise ResumeImportError(f"records 超过单批上限 {MAX_RECORDS}")
    referrer = body.get("referrer")
    if referrer is not None and (not isinstance(referrer, str) or len(referrer) > 64):
        raise ResumeImportError("referrer 必须为字符串且 ≤64 字符")
    valid, errors = [], []
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            errors.append({"index": idx, "reason": "记录必须为对象"})
            continue
        if not rec.get("name"):
            errors.append({"index": idx, "reason": "name 为导入必填字段"})
            continue
        unknown = set(rec) - KNOWN_FIELDS
        if unknown:
            errors.append({"index": idx, "reason": f"未知字段: {sorted(unknown)}"})
            continue
        try:
            validate_candidate_json(rec)
        except Exception as exc:  # noqa: BLE001
            errors.append({"index": idx, "reason": str(exc)})
            continue
        valid.append(rec)
    return body, valid, errors


def parse_csv_bytes(data: bytes) -> tuple[list[dict], list[dict]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ResumeImportError("CSV 必须为 UTF-8 编码") from exc
    reader = csv.DictReader(io.StringIO(text), restkey="__extra__")
    if reader.fieldnames != CSV_HEADERS or len(set(reader.fieldnames or [])) != len(CSV_HEADERS):
        raise ResumeImportError(f"CSV 表头必须为固定列序: {CSV_HEADERS}")
    rows, errors = [], []
    for line_no, row in enumerate(reader, start=2):
        if row.pop("__extra__", None):
            errors.append({"row_no": line_no, "reason": "CSV 列数超过固定表头"})
            continue
        if row.get("skills"):
            row["skills"] = row["skills"].split(";")
        # 空串 → None
        row = {k: (None if v == "" else v) for k, v in row.items()}
        overlong = False
        for desc_key in ("max_education_desc", "max_work_desc"):
            v = row.get(desc_key)
            if v is not None and len(v) > MAX_FIELD_LEN:
                errors.append({"row_no": line_no, "reason": f"{desc_key} 超过 {MAX_FIELD_LEN} 字符"})
                overlong = True
        if overlong:
            continue
        record = {k: row.get(k) for k in KNOWN_FIELDS if k in row}
        record["education"] = record["work"] = record["project"] = None
        if not record.get("name"):
            errors.append({"row_no": line_no, "reason": "name 为导入必填字段"})
            continue
        try:
            validate_candidate_json(record)
        except Exception as exc:  # noqa: BLE001
            errors.append({"row_no": line_no, "reason": str(exc)})
            continue
        record["import_summary"] = {
            "education": row.get("max_education_desc"),
            "work": row.get("max_work_desc"),
        }
        rows.append({"row_no": line_no, "row_hash": row_hash(record), "data": record})
    return rows, errors


def write_record_file(upload_dir: str, workspace_id: int, record: dict, meta: dict) -> tuple[str, int]:
    """A-17：每个导入记录落独立 JSON 文件，供 1 run : 1 candidate 幂等消费。"""
    payload = json.dumps({"record": record, "meta": meta}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path = os.path.join(upload_dir, f"{workspace_id}-import-{uuid.uuid4().hex}.json")
    with open(path, "wb") as out:
        out.write(payload)
    return path, len(payload)