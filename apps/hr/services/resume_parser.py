# coding=utf-8
"""
    @project: MaxKB
    @file： resume_parser.py
    @desc：简历文本提取与字段抽取：基础字段走规则型抽取（不调用模型，无法确定一律留空）；
          技能提取可选 LLM 增强（extract_skills_llm，chat_fn 由调用方注入，失败回退规则结果）。
"""
import json
import re

def _extract_after(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip().strip(":：，,。;；")
            if value:
                return value
    return ""


def parse_resume_text(text):
    """身份字段抽取：只提取可靠的正则字段（姓名/邮箱/手机）。

    其余字段（城市/学历/年限/技能/备注）不做规则解析——正则不可靠且随简历版式差异大，
    统一由切片与混合检索按需处理（设计：LLM 只做切片，检索用 关键字+稀疏+密集 三路）。
    """
    name = _extract_after(text, [r"姓名[:：;；]\s*([^\n；;]{2,8})", r"(?m)^([\u4e00-\u9fa5]{2,4})$"])
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    phone_match = re.search(r"(?:\+?86[- ]?)?1[3-9]\d{9}", text)
    return {
        "name": name,
        "email": email_match.group(0) if email_match else "",
        "phone": phone_match.group(0) if phone_match else "",
        "current_city": "",
        "target_city": "",
        "highest_degree": "",
        "years_experience": None,
        "skills": [],
        "note": "",
    }


_SKILLS_PROMPT_TEMPLATE = """你是中文简历技能分析师。任务：从简历文本中提取候选人掌握的专业技能、工具与核心能力。

严格规则：
1. 只输出 JSON 数组，例如 ["Python", "市场营销", "新媒体运营"]，不要输出任何其他内容；
2. 每个技能是 2~12 个字的短语，不要整句、不要带序号、不要带"负责/熟悉/擅长"等修饰语；
3. 只提取明确的技能/工具/软件/专业能力，忽略姓名、公司名、时间、个人信息；
4. 输出 3~15 个技能，按重要性排序。

简历文本：
{text}"""


def extract_skills_llm(text, chat_fn, max_skills=15):
    """用 LLM 从简历全文中提取技能（覆盖技能散落在工作经历、无专门技能栏的简历）。

    返回清洗后的技能列表；调用失败/输出不合法返回 []，由调用方决定是否回退规则结果。
    """
    if not text or not text.strip():
        return []
    try:
        raw = chat_fn(_SKILLS_PROMPT_TEMPLATE.format(text=text[:6000]))
    except Exception:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        match = re.search(r"\[.*?\]", raw, re.S)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except (ValueError, TypeError):
            return []
    if not isinstance(parsed, list):
        return []
    skills = []
    seen = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        skill = item.strip().strip('\"\'，。；')
        if not skill:
            continue
        if len(skill) > 30 or len(skill) < 2:
            continue
        if '\n' in skill or '：' in skill or '负责' in skill or '熟悉' in skill:
            continue
        key = skill.lower()
        if key in seen:
            continue
        seen.add(key)
        skills.append(skill)
        if len(skills) >= max_skills:
            break
    return skills


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
