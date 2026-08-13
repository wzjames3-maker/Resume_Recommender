import copy
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, CandidateOverride, CandidateRevision

_PATH_RE = re.compile(r"[a-zA-Z_]+|\[\d+\]")


def _parse_path(path: str) -> list:
    """'work[0].title' → [('key','work'), ('idx',0), ('key','title')]"""
    tokens = []
    for part in _PATH_RE.findall(path):
        if part.startswith("["):
            tokens.append(("idx", int(part[1:-1])))
        else:
            tokens.append(("key", part))
    if not tokens:
        raise ValueError(f"非法字段路径: {path}")
    return tokens


def get_path(obj: dict, path: str):
    """读取路径值；不存在返回 None。"""
    node = obj
    for kind, token in _parse_path(path):
        if kind == "idx":
            if not isinstance(node, list) or token >= len(node):
                return None
            node = node[token]
        else:
            if not isinstance(node, dict) or token not in node:
                return None
            node = node[token]
    return node


def set_path(obj: dict, path: str, value, *, clear: bool = False) -> dict:
    """按索引路径写入/清除值，返回新 dict（不原地改）。

    中间节点若为标量/缺失，会创建容器并**写回父节点**（避免静默丢写）。
    """
    result = copy.deepcopy(obj)
    tokens = _parse_path(path)
    parent, parent_key = None, None
    node = result
    for i, (kind, token) in enumerate(tokens):
        last = i == len(tokens) - 1
        if kind == "idx":
            if not isinstance(node, list):
                node = []
                if parent is not None:
                    parent[parent_key] = node
            while len(node) <= token:
                node.append(None)
            if last:
                node[token] = None if clear else value
            else:
                nxt = node[token]
                if not isinstance(nxt, (dict, list)):
                    nxt = [] if tokens[i + 1][0] == "idx" else {}
                    node[token] = nxt
                parent, parent_key, node = node, token, nxt
        else:
            if not isinstance(node, dict):
                node = {}
                if parent is not None:
                    parent[parent_key] = node
            if last:
                node[token] = None if clear else value
            else:
                nxt = node.setdefault(token, {})
                parent, parent_key, node = node, token, nxt
    return result


def apply_overrides(base: dict, overrides: list) -> dict:
    """按 override/clear 作用域顺序应用。同一字段多个 override 时后写覆盖先写。"""
    merged = dict(base)
    for ov in overrides:
        action = ov["action"]
        if action == "override":
            merged = set_path(merged, ov["field_path"], ov["after_value"])
        elif action == "clear":
            merged = set_path(merged, ov["field_path"], None)
    return merged


async def build_effective_view(db: AsyncSession, candidate_id: int) -> dict:
    """候选人详情合并视图：latest revision 解析值 + override/clear + 画像（spec §2）。"""
    cand = await db.get(Candidate, candidate_id)
    if cand is None:
        raise ValueError(f"候选人不存在: {candidate_id}")
    rev = (await db.execute(select(CandidateRevision).where(
        CandidateRevision.id == cand.latest_revision_id))).scalar_one_or_none()
    base = dict(rev.candidate_json) if rev else dict(cand.structured_data or {})
    overrides = (await db.execute(select(CandidateOverride).where(
        CandidateOverride.candidate_id == candidate_id))).scalars().all()
    fields = apply_overrides(base, [{"field_path": o.field_path, "action": o.action.value,
                                     "after_value": o.after_value} for o in overrides])
    profile = (rev.profile_json or {}).get("values") or {} if rev else {}
    return {
        "candidate_id": candidate_id,
        "name": cand.name,
        "status": cand.status.value,
        "deleted_until": cand.deleted_until.isoformat() if cand.deleted_until else None,
        "fields": fields,
        "profile": profile,
        "latest_revision_id": cand.latest_revision_id,
    }