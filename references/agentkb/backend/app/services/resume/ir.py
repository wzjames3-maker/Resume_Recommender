from datetime import UTC, datetime

from app.services.resume.blocks import Block, BlockKind

IR_VALID_CHARS_THRESHOLD = 200  # 与 PRD F6 / 评测 spec §2.5 冻结一致


def _yaml_header(source_channel: str, parser: str, fmt: str) -> str:
    now = datetime.now(UTC).isoformat()
    return (
        "---\n"
        f"source_channel: {source_channel}\n"
        f"parser: {parser}\n"
        f"parse_time: {now}\n"
        f"format: {fmt}\n"
        "---\n"
    )


def _block_to_markdown(block: Block) -> list[str]:
    lines = [f"<!-- block_id: {block.block_id} kind: {block.kind.value} -->"]
    if block.kind is BlockKind.table:
        # 表格保留 markdown 表格语法：首行作为表头，表格不展平
        rows = block.content.split("\n")
        lines.append("| " + " | ".join(c.strip() for c in rows[0].split("|")) + " |")
        lines.append("|" + "|".join(["---"] * len(rows[0].split("|"))) + "|")
        for row in rows[1:]:
            lines.append("| " + " | ".join(c.strip() for c in row.split("|")) + " |")
    else:
        lines.append(block.content)
    return lines


def build_ir(blocks: list[Block], source_channel: str, parser: str, fmt: str) -> str:
    parts = [_yaml_header(source_channel, parser, fmt)]
    for block in blocks:
        parts.extend(_block_to_markdown(block))
        parts.append("")
    return "\n".join(parts)


def count_valid_chars(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def validate_ir(ir: str) -> None:
    if count_valid_chars(ir) < IR_VALID_CHARS_THRESHOLD:
        raise ValueError(f"IR 有效字符低于下限 {IR_VALID_CHARS_THRESHOLD}，抽取失败")


_ARRAY_LABELS = {"education": "教育经历", "work": "工作经历", "project": "项目经历"}


def build_import_ir(record: dict, source_channel: str) -> str:
    """csv/json 结构化导入的 IR：由结构化字段与 import_summary 生成（PRD F6 ③）。

    不走有效字符阈值判定（PRD：不以 JSON/CSV 语法字符数判断 IR 失败）。
    """
    lines = [
        "---",
        f"source_channel: {source_channel}",
        "parser: structured-import/0.1",
        f"parse_time: {datetime.now(UTC).isoformat()}",
        "format: import",
        "---",
        "",
    ]
    for key, value in record.items():
        if value in (None, "", [], {}):
            continue
        if key == "import_summary":
            for part, text in value.items():
                if text:
                    lines.append(f"{part}: {text}")
        elif key in _ARRAY_LABELS:
            lines.append(f"## {_ARRAY_LABELS[key]}")
            for item in value:
                lines.append(" | ".join(str(v) for v in item.values() if v not in (None, "")))
        elif key == "skills":
            lines.append("技能: " + "、".join(value))
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)