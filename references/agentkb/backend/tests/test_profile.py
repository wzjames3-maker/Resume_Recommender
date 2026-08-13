import pytest

from app.services.resume.profile import (
    ProfileValidationError,
    generate_profile,
    validate_profile_json,
)


def _valid_profile() -> dict:
    return {
        "level": "Mid",
        "professional_depth": "Medium",
        "domain": "金融科技",
        "influence_scope": "个人贡献者",
        "management": "无",
        "stability": "正常",
        "growth_trend": "平稳",
        "communication": "中",
        "strengths": "熟悉支付系统",
        "risks": "稳定性一般",
        "career_pattern": "后端为主",
    }


def test_valid_profile_passes():
    validate_profile_json(_valid_profile())


def test_invalid_enum_rejected():
    p = _valid_profile()
    p["level"] = "SuperSenior"
    with pytest.raises(ProfileValidationError):
        validate_profile_json(p)


def test_null_enum_allowed():
    p = _valid_profile()
    p["level"] = None
    validate_profile_json(p)


@pytest.mark.asyncio
async def test_generate_profile_returns_null_on_no_evidence():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"profile": {"level": None}, "evidence": {}}

    result = await generate_profile(FakeLLM(), {"name": "张三"}, {})
    assert result.profile["level"] is None


@pytest.mark.asyncio
async def test_generate_profile_requires_candidate_evidence_for_non_null_conclusion():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"profile": {"level": "Mid"}, "evidence": {"level": ["work[0].content"]}}

    result = await generate_profile(FakeLLM(), {"work": [{"content": "支付系统"}]},
                                    {"work[0].content": {"block_id": 1}})
    assert result.evidence == {"level": ["work[0].content"]}


@pytest.mark.asyncio
async def test_generate_profile_prompt_excludes_pii():
    # 候选人对象此时已含还原后的明文 PII（C-1 流程），出站 prompt 必须剔除
    seen = {}

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            seen["user"] = user
            return {"profile": {"level": None}, "evidence": {}}

    await generate_profile(FakeLLM(), {"name": "张三", "phone": "13800000000",
                                       "email": "a@b.com", "city": "杭州"}, {})
    # A-15：phone/email/姓名均不出站（画像分析不需要身份字段）
    assert "13800000000" not in seen["user"]
    assert "a@b.com" not in seen["user"]
    assert "张三" not in seen["user"]