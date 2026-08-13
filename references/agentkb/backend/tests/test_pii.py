import pytest

from app.services.resume.pii import (
    PIIRedactionError,
    PIIType,
    desensitize_text,
    identify_pii,
    restore_pii_values,
)


def test_identify_phone_and_email():
    spans = identify_pii("联系方式：13800000000 或 zhangsan@example.com")
    types = {s.pii_type for s in spans}
    assert types == {PIIType.phone, PIIType.email}
    assert spans[0].value == "13800000000"


def test_identify_id_card():
    spans = identify_pii("身份证号 110101199001011234")
    assert any(s.pii_type == PIIType.id_card for s in spans)


def test_identify_name_by_hint():
    # A-15：提示词式姓名（「姓名: X」）识别为 name 类 PII
    spans = identify_pii("姓名：张三 电话 13800000000")
    names = [s for s in spans if s.pii_type == PIIType.name]
    assert names and names[0].value == "张三"


def test_identify_name_by_contact_label():
    # 标签式姓名（「联系人: X」）同样识别为 name 类 PII，防止随 IR/embedding 出站
    spans = identify_pii("联系人：李四 电话 13900000000")
    names = [s for s in spans if s.pii_type == PIIType.name]
    assert names and names[0].value == "李四"


def test_identify_english_name_by_label():
    masked, mapping = desensitize_text("Name: Jane Doe")
    assert "Jane Doe" not in masked
    assert any(entry.pii_type is PIIType.name for entry in mapping)


def test_identify_english_name_by_contact_label():
    masked, mapping = desensitize_text("Contact: Bob Smith")
    assert "Bob Smith" not in masked
    assert any(entry.pii_type is PIIType.name for entry in mapping)


def test_desensitize_replaces_with_token():
    masked, mapping = desensitize_text("电话 13800000000，邮箱 a@b.com")
    assert "13800000000" not in masked
    assert "a@b.com" not in masked
    assert mapping, "应返回映射"
    assert all(m.token and m.token.startswith("PII:") for m in mapping)


def test_desensitize_roundtrip_via_mapping():
    masked, mapping = desensitize_text("电话 13800000000")
    assert mapping[0].value == "13800000000"
    assert mapping[0].token in masked


def test_desensitize_is_deterministic():
    # evidence 引用脱敏后 IR（A-13）：同一输入重复脱敏结果必须一致，才可重放校验
    a, _ = desensitize_text("姓名：张三 电话 13800000000")
    b, _ = desensitize_text("姓名：张三 电话 13800000000")
    assert a == b


def test_restore_pii_values():
    _masked, mapping = desensitize_text("电话 13800000000，邮箱 a@b.com")
    obj = {"phone": mapping[0].token, "email": mapping[1].token,
           "work": [{"content": f"联系 {mapping[0].token}"}], "city": None}
    restored = restore_pii_values(obj, mapping)
    assert restored["phone"] == "13800000000"
    assert restored["email"] == "a@b.com"
    assert "13800000000" in restored["work"][0]["content"]
    assert restored["city"] is None


def test_fail_closed_on_desensitize_error():
    # 孤立代理对无法编码为 UTF-8：脱敏必须抛 PIIRedactionError 而非静默放行
    with pytest.raises(PIIRedactionError):
        desensitize_text("\ud800")


def test_identify_labeled_address():
    masked, mapping = desensitize_text("现住址：浙江省杭州市西湖区文三路 90 号 2 楼\n技能：Python")
    assert "浙江省杭州市西湖区文三路 90 号 2 楼" not in masked
    assert any(entry.pii_type is PIIType.address for entry in mapping)


def test_identify_labeled_address_with_trailing_field_on_same_line():
    # 同行尾随字段（电话等）不得使整行地址结构化校验失败而泄漏
    masked, mapping = desensitize_text("现住址：浙江省杭州市西湖区文三路 90 号 电话 13800000000")
    assert "浙江省杭州市西湖区文三路 90 号" not in masked
    assert "13800000000" not in masked
    assert any(entry.pii_type is PIIType.address for entry in mapping)
    assert any(entry.pii_type is PIIType.phone for entry in mapping)


def test_identify_structured_address_without_label():
    masked, mapping = desensitize_text("浙江省杭州市西湖区文三路 90 号\nJava 后端工程师")
    assert "浙江省杭州市西湖区文三路 90 号" not in masked
    assert any(entry.pii_type is PIIType.address for entry in mapping)


def test_identify_structured_residential_address_without_label():
    masked, mapping = desensitize_text("浙江省杭州市西湖区翠苑小区")
    assert "浙江省杭州市西湖区翠苑小区" not in masked
    assert any(entry.pii_type is PIIType.address for entry in mapping)


@pytest.mark.parametrize(
    "text",
    [
        "项目地址：支付系统重构",
        "项目地址：浙江省杭州市西湖区文三路 90 号",
        "公司地址：浙江省杭州市西湖区文三路 90 号",
        "Address: Backend Engineer",
        "杭州科技有限公司，办公地址位于文三路",
        "项目部署在杭州市，机房编号为 3 号",
        "杭州",
        "籍贯：杭州",
        "总部设在浙江省杭州市西湖区文三路 90 号",
        "杭州市创新科技有限公司办公地址文三路90号",
        "杭州市项目部署文三路90号",
        "杭州市西湖区支付项目研发楼",
        "杭州市西湖区后端技能培训楼",
    ],
)
def test_does_not_redact_business_or_location_text_as_address(text):
    masked, mapping = desensitize_text(text)
    assert masked == text
    assert not any(entry.pii_type is PIIType.address for entry in mapping)


@pytest.mark.parametrize(
    "text",
    [
        "Company Name: Acme Inc",
        "Project Name: Hiring Platform",
        "Skill Name: Python",
        "Name of the company is Acme",
    ],
)
def test_does_not_identify_name_in_business_label_value(text):
    masked, mapping = desensitize_text(text)
    assert masked == text
    assert not any(entry.pii_type is PIIType.name for entry in mapping)


def test_does_not_identify_contact_without_colon_as_name():
    # Contact 无冒号是正文短语，不是姓名标签（电话仍单独脱敏）
    masked, mapping = desensitize_text("Contact me at 13800000000")
    assert not any(entry.pii_type is PIIType.name for entry in mapping)
    assert "13800000000" not in masked


def test_does_not_identify_header_first_line_as_name():
    text = "---\nformat: docx\n---\n\n华为\n<!-- block_id: 1 kind: paragraph -->\n工作经历"
    masked, mapping = desensitize_text(text)
    assert masked == text
    assert mapping == []


def test_does_not_redact_city_or_work_content_as_address_or_name():
    text = "杭州\n<!-- block_id: 1 kind: paragraph -->\n在北京创新科技有限公司负责支付项目"
    masked, mapping = desensitize_text(text)
    assert masked == text
    assert mapping == []
