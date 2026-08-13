import pytest

from app.services.resume.schema import SchemaValidationError, validate_candidate_json
from app.services.resume.structured import (
    FailureClass,
    classify_failure,
    extract_candidate,
)


def _valid_candidate() -> dict:
    return {
        "name": "张三",
        "gender": "男",
        "birth_month": "1995-03",
        "phone": "13800000000",
        "email": "zhangsan@example.com",
        "highest_degree": "本科",
        "city": "杭州",
        "expected_city": "杭州",
        "expected_position": "Java 后端",
        "skills": ["Java", "Spring"],
        "education": [{"school": "H 大学", "degree": "本科", "major": "计算机", "start": "2013-09", "end": "2017-06"}],
        "work": [{"company": "A 公司", "title": "后端工程师", "content": "负责支付系统", "start": "2017-07", "end": "2021-06", "type": "full_time"}],
        "project": [],
    }


def test_valid_candidate_passes():
    validate_candidate_json(_valid_candidate())


def test_unknown_enum_rejected():
    c = _valid_candidate()
    c["gender"] = "未知"
    with pytest.raises(SchemaValidationError):
        validate_candidate_json(c)


def test_bad_date_format_rejected():
    c = _valid_candidate()
    c["birth_month"] = "1995/03"
    with pytest.raises(SchemaValidationError):
        validate_candidate_json(c)


def test_too_long_field_rejected():
    c = _valid_candidate()
    c["name"] = "x" * 2001
    with pytest.raises(SchemaValidationError):
        validate_candidate_json(c)


def test_unknown_field_rejected():
    c = _valid_candidate()
    c["fabricated_field"] = "xxx"
    with pytest.raises(SchemaValidationError, match="未知字段"):
        validate_candidate_json(c)


def test_work_type_enum():
    c = _valid_candidate()
    c["work"][0]["type"] = "remote"
    with pytest.raises(SchemaValidationError):
        validate_candidate_json(c)


def test_classify_failure():
    assert classify_failure(SchemaValidationError("x")) is FailureClass.not_retryable
    assert classify_failure(TimeoutError()) is FailureClass.retryable
    assert classify_failure(ValueError("rate limit")) is FailureClass.retryable


_IR = ("---\nsource_channel: job_site\n---\n\n"
       "<!-- block_id: 1 kind: paragraph -->\n姓名：张三 电话 13800000000\n")


def _masked_block_text() -> str:
    # evidence 校验针对脱敏后 IR（A-13）；先重放脱敏拿到 block 文本与 token
    from app.services.resume.pii import desensitize_text
    masked, _ = desensitize_text("姓名：张三 电话 13800000000")
    return masked


@pytest.mark.asyncio
async def test_extract_candidate_restores_pii_and_verifies_evidence():
    block = _masked_block_text()          # 形如 "姓名：PII:name:0 电话 PII:phone:1"
    name_token = block.split("：")[1].split()[0]

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"candidate": {"name": name_token, "phone": "PII:phone:1"},
                    "evidence": {
                        "name": {"block_id": 1, "start_offset": 0,
                                 "end_offset": len(name_token), "quote": name_token},
                        "phone": {"block_id": 1, "start_offset": 0,
                                  "end_offset": len("PII:phone:1"), "quote": "PII:phone:1"},
                    }}

    out = await extract_candidate(FakeLLM(), _IR, "job_site")
    assert out.candidate["phone"] == "13800000000"      # token 已还原（C-1）
    ev = out.evidence["name"]
    assert ev["quote_hash"] and len(ev["quote_hash"]) == 16
    assert "quote" not in ev                              # 落库形态只留 hash（A-12/A-13）
    assert out.pii_mapping, "必须返回脱敏映射供入库持久化"


@pytest.mark.asyncio
async def test_extract_candidate_rejects_fabricated_evidence():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"candidate": {"name": "PII:name:0"},
                    "evidence": {"name": {"block_id": 1, "start_offset": 0,
                                           "end_offset": 4, "quote": "编造的引用"}}}

    with pytest.raises(SchemaValidationError):
        await extract_candidate(FakeLLM(), _IR, "job_site")


# 任务 5：出站回归样本（标签式姓名 + 地址 + 电话），与画像/embedding 测试复用同一 candidate 语义。
_SAMPLE_IR = ("---\nformat: docx\n---\n\n"
              "姓名：张三\n"
              "现住址：浙江省杭州市西湖区文三路 90 号\n"
              "电话 13800000000\n"
              "<!-- block_id: 1 kind: paragraph -->\n"
              "负责支付系统\n")


# 任务 5：结构化调用点出站脱敏（A-15）。样本姓名采标签式（任务 1 仅标签式姓名识别），
# 地址与电话为真实 PII。
@pytest.mark.asyncio
async def test_extract_candidate_masks_pii_before_outbound():
    captured: dict[str, str] = {}

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            captured["user"] = user
            return {"candidate": {"name": "PII:name:0", "phone": "PII:phone:2",
                                   "skills": ["Java"], "work": [], "project": [], "education": []},
                    "evidence": {}}

    await extract_candidate(FakeLLM(), _SAMPLE_IR, "job_site")

    user = captured["user"]
    assert "张三" not in user
    assert "浙江省杭州市西湖区文三路 90 号" not in user
    assert "13800000000" not in user
    assert "PII:name:" in user
    assert "PII:address:" in user
    assert "PII:phone:" in user
