from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, CandidateRevision
from app.services.search.schema import DEGREE_ORDINAL


def match_conditions(sd: dict, profile: dict, conditions: list) -> list[str]:
    """返回该候选命中的条件字段路径（S-9 命中标注）。画像字段读 profile，其余读 structured_data。"""
    matched = []
    for cond in conditions:
        if cond.get("value") is None:
            continue
        fields = [cond["field"]] if "field" in cond else list(cond["fields"])
        op, value = cond["op"], cond["value"]
        resolved = {f: (profile.get(f) if f in ("level", "domain", "management") else sd.get(f)) for f in fields}
        if op == "contains" and fields == ["skills"]:
            skills = [s.lower() for s in (sd.get("skills") or [])]
            if any(str(v).lower() in skills for v in value):
                matched.append("skills")
        elif op == "contains_text":
            for f in fields:
                if str(resolved.get(f) or "").lower().find(str(value).lower()) >= 0:
                    matched.append(f)
                    break
        elif op == "any_match":
            if any(str(resolved.get(f)) == str(value) for f in fields):
                matched.append("|".join(fields))
        elif op == ">=" and fields == ["years_experience"]:
            try:
                if int(sd.get("years_experience") or -1) >= int(value):
                    matched.append("years_experience")
            except (TypeError, ValueError):
                pass
        elif op == "range_degree" and fields == ["highest_degree"]:
            if DEGREE_ORDINAL.get(sd.get("highest_degree"), 0) >= DEGREE_ORDINAL.get(value, 99):
                matched.append("highest_degree")
        elif op == "eq":
            for f in fields:
                if str(resolved.get(f)) == str(value):
                    matched.append(f)
    return matched


async def build_candidate_cards(db: AsyncSession, candidate_ids: list[int], conditions: list) -> list[dict]:
    if not candidate_ids:
        return []
    rows = await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
    cands = {c.id: c for c in rows.scalars().all()}
    rev_rows = await db.execute(
        select(CandidateRevision.candidate_id, CandidateRevision.profile_json)
        .join(Candidate, Candidate.latest_revision_id == CandidateRevision.id)
        .where(Candidate.id.in_(candidate_ids))
    )
    profiles = {cid: (pj or {}).get("values") or {} for cid, pj in rev_rows}
    cards = []
    for cid in candidate_ids:
        c = cands.get(cid)
        if c is None:
            continue
        sd = c.structured_data or {}
        profile = profiles.get(cid) or {}
        cards.append({
            "candidate_id": cid,
            "name": c.name,
            "city": sd.get("city"),
            "expected_city": sd.get("expected_city"),
            "highest_degree": sd.get("highest_degree"),
            "years_experience": sd.get("years_experience"),
            "expected_position": sd.get("expected_position"),
            "skills": sd.get("skills") or [],
            "matched_conditions": match_conditions(sd, profile, conditions),
            "profile": {"level": profile.get("level"), "domain": profile.get("domain")},
        })
    return cards