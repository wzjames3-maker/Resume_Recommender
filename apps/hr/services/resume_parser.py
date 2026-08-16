# coding=utf-8
"""
    @project: MaxKB
    @file： resume_parser.py
    @desc：简历文本提取与规则型字段抽取（不调用模型，无法确定一律留空）
"""
import re

_DEGREES = ["博士", "硕士", "本科", "大专", "中专", "高中"]

# OCR 分号流/表格简历的关键词覆盖（A2 增强）：现居/籍贯/户籍等 + 技能变体
_CITY_KEYWORDS = r"(?:现居城市|现居|现居住|所在城市|籍贯|户籍|户口|家庭住址|所在地区)"
_SKILL_KEYWORDS = r"(?:个人技能|技能特长|专业技能|掌握技能|技能|特长)"


def _normalize_city(raw):
    """城市粒度归一：去省/自治区/特别行政区前缀与「市」后缀（「新疆省阿克苏市」→「阿克苏」、「北京市」→「北京」）。"""
    text = raw.strip()
    for token in ("特别行政区", "自治区", "省"):
        idx = text.find(token)
        if idx != -1:
            text = text[idx + len(token):]
            break
    for city in ("北京", "上海", "天津", "重庆"):
        if text.startswith(city + "市"):
            return city
    return text.rstrip("市")


def _extract_after(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip().strip(":：，,。;；")
            if value:
                return value
    return ""


def _split_skills(section):
    if not section:
        return []
    parts = re.split(r"[，,、;；/|]\s*", section.strip())
    return [part.strip() for part in parts if part.strip()]


def parse_resume_text(text):
    name = _extract_after(text, [r"姓名[:：]\s*([^\n]{2,8})", r"(?m)^([\u4e00-\u9fa5]{2,4})$"])
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    phone_match = re.search(r"(?:\+?86[- ]?)?1[3-9]\d{9}", text)
    current_city = _normalize_city(_extract_after(text, [_CITY_KEYWORDS + r"[:：;；]?\s*([\u4e00-\u9fa5]{2,12})"]))
    target_city = _normalize_city(_extract_after(text, [r"(?:期望城市|意向城市|目标城市)[:：;；]\s*([\u4e00-\u9fa5]{2,12})"]))
    degree = ""
    for value in _DEGREES:
        if re.search(re.escape(value), text):
            degree = value
            break
    years_match = re.search(
        r"(\d+)\s*年(?:工作经验|经验|工作经历|以上)|工作(?:年限|年数)?[:：;；]?\s*(\d+)\s*年", text
    )
    years = int(years_match.group(1) or years_match.group(2)) if years_match else None
    skills = _split_skills(_extract_after(text, [
        _SKILL_KEYWORDS + r"[:：;；]?\s*([^\n]{1,500}?)(?=\s*(?:教育背景|工作经历|项目经验|项目经历|自我评价|个人优势|兴趣爱好|期望职位|出生年月|$))"
    ]))

    note_parts = []
    for section_name, patterns in (
        ("教育经历", [r"教育经历[:：]?\s*\n(.*?)(?:\n\s*(?:工作经历|项目经历|自我评价)|$)"]),
        ("工作经历", [r"工作经历[:：]?\s*\n(.*?)(?:\n\s*(?:教育经历|项目经历|自我评价)|$)"]),
    ):
        section = _extract_after(text, patterns)
        if section:
            note_parts.append(f"{section_name}：{section.strip()}")

    return {
        "name": name,
        "email": email_match.group(0) if email_match else "",
        "phone": phone_match.group(0) if phone_match else "",
        "current_city": current_city,
        "target_city": target_city,
        "highest_degree": degree,
        "years_experience": years,
        "skills": skills,
        "note": "\n".join(note_parts),
    }


def extract_text_from_docx(file_path):
    """
    提取 docx 文本：正文段落 + 表格单元格（合并单元格去重，按行序拼接）。
    实测真实简历（数据集 sample）为表格排版，仅 document.paragraphs 会丢失全部内容。
    """
    from docx import Document

    document = Document(file_path)
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    seen_cells = set()
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip() and cell._tc not in seen_cells:
                    seen_cells.add(cell._tc)
                    parts.append(cell.text.strip())
    return "\n".join(parts)


def extract_text_from_txt(file_path):
    for encoding in ("utf-8", "gbk"):
        try:
            with open(file_path, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError:
            continue
    raise ValueError("无法解码文本文件")
