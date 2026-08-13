import pytest

from app.services.resume.blocks import Block, BlockKind
from app.services.resume.ir import (
    IR_VALID_CHARS_THRESHOLD,
    build_ir,
    count_valid_chars,
    validate_ir,
)


def test_build_ir_has_yaml_header():
    blocks = [
        Block(BlockKind.paragraph, "基本技能", 1),
        Block(BlockKind.table, "姓名 | 张三\n电话 | 13800000000", 2),
    ]
    ir = build_ir(blocks, source_channel="job_site", parser="docx/0.1", fmt="docx")
    assert "source_channel: job_site" in ir
    assert "parser: docx/0.1" in ir
    assert "| 姓名 | 张三 |" in ir or "姓名 | 张三" in ir


def test_count_valid_chars_ignores_whitespace():
    assert count_valid_chars("张 三\n\n  电话  ") == 4  # 张三电话


def test_validate_ir_below_threshold_fails():
    with pytest.raises(ValueError, match="有效字符"):
        validate_ir("a" * (IR_VALID_CHARS_THRESHOLD - 1))


def test_validate_ir_above_threshold_passes():
    validate_ir("好" * IR_VALID_CHARS_THRESHOLD)  # 不抛


def test_build_import_ir_from_structured_record():
    # PRD F6 ③：csv/json 结构化导入由字段生成 IR/检索文本，不做字符数阈值判定
    from app.services.resume.ir import build_import_ir
    record = {"name": "张三", "skills": ["Java", "Spring"],
              "work": [{"company": "A 公司", "title": "后端工程师", "content": "负责支付系统"}],
              "import_summary": {"education": "H 大学本科", "work": "A 公司 4 年"}}
    ir = build_import_ir(record, source_channel="referral")
    assert "source_channel: referral" in ir
    assert "A 公司" in ir and "负责支付系统" in ir
    assert "H 大学本科" in ir  # import_summary 供检索（schema spec §4）
    assert "Java" in ir