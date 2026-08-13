from app.services.resume.pii import desensitize_text


def _join(*parts: list[str]) -> str:
    return " ".join(p for p in parts if p)


def build_segments(candidate: dict) -> dict[str, str]:
    education = " ".join(
        f"{e.get('school', '')} {e.get('degree', '')} {e.get('major', '')} {e.get('start', '')} {e.get('end', '')}"
        for e in candidate.get("education") or []
    )
    work = " ".join(
        f"{w.get('company', '')} {w.get('title', '')} {w.get('content', '')}".strip()
        for w in candidate.get("work") or []
    )
    project = " ".join(
        f"{p.get('name', '')} {p.get('responsibility', '')}".strip()
        for p in candidate.get("project") or []
    )
    skills = " ".join(candidate.get("skills") or [])
    # A-15：summary 会发送给 embedding 服务，不含姓名/联系电话等身份 PII。
    summary = _join(
        candidate.get("city", ""),
        candidate.get("expected_city", ""), candidate.get("expected_position", ""),
        candidate.get("highest_degree", ""),
    )
    return {
        "summary": summary,
        "education": education,
        "work": work,
        "project": project,
        "skills": skills,
    }


def build_search_text(candidate: dict) -> str:
    """本地全文索引文本：不含 phone/email，保留姓名/技能等本地检索字段。"""
    parts = []
    for key, value in candidate.items():
        if key in {"phone", "email"} or value in (None, ""):
            continue
        if key == "import_summary" and isinstance(value, dict):
            parts.append(" ".join(str(v) for v in value.values() if v))
        elif key == "name":
            # 姓名只在本地索引中保留；不带「姓名:」提示以免被出站 PII 规则替换为 token。
            parts.append(str(value))
        elif isinstance(value, list):
            parts.append(f"{key}:" + " ".join(str(v) for v in value))
        elif not isinstance(value, dict):
            parts.append(f"{key}:{value}")
    raw = " ".join(parts)
    masked, _ = desensitize_text(raw)
    return masked