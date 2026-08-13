import pytest

from app.services.resume.importers import (
    MAX_FIELD_LEN,
    MAX_RECORDS,
    ResumeImportError,
    parse_csv_bytes,
    parse_json_envelope,
)

_CSV_HEADER = "name,gender,birth_month,phone,email,highest_degree,city,expected_city,expected_position,skills,max_education_desc,max_work_desc"


def test_csv_overlong_summary_field_rejected():
    long_desc = "x" * (MAX_FIELD_LEN + 1)
    csv_text = f"{_CSV_HEADER}\n张三,,,,,,,,,,{long_desc},"
    rows, errors = parse_csv_bytes(csv_text.encode("utf-8"))
    assert rows == []
    assert errors and "max_education_desc" in errors[0]["reason"]


def test_csv_normal_row_ok():
    csv_text = f"{_CSV_HEADER}\n张三,,,,,,,,,Java,,"
    rows, errors = parse_csv_bytes(csv_text.encode("utf-8"))
    assert errors == []
    assert rows and rows[0]["data"]["name"] == "张三"
    assert rows[0]["data"]["skills"] == ["Java"]


def test_json_envelope_records_over_limit():
    body = {
        "upload_id": "big-1",
        "schema_version": "resume-import/v1",
        "template_version": "2026-08-07.1",
        "source_channel": "referral",
        "records": [{"name": f"候选人{i}"} for i in range(MAX_RECORDS + 1)],
    }
    with pytest.raises(ResumeImportError, match="上限"):
        parse_json_envelope(body)