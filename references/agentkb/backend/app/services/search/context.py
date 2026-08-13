import json


def _field_key(cond: dict) -> str:
    return "|".join(sorted(cond["fields"])) if "fields" in cond else cond["field"]


def merge_follow_up(prior: list, change: list) -> list:
    """follow_up：以上轮条件为基线，仅应用本轮变化字段（S-5）。value=None 表示删除该条件。"""
    merged = [dict(c) for c in prior]
    for ch in change:
        key = _field_key(ch)
        if ch.get("value") in (None, [], ""):
            merged = [c for c in merged if _field_key(c) != key]
            continue
        replaced = False
        for i, c in enumerate(merged):
            if _field_key(c) == key:
                merged[i] = dict(ch)
                replaced = True
                break
        if not replaced:
            merged.append(dict(ch))
    return merged


def serialize_context(ctx: dict) -> str:
    return json.dumps(ctx, ensure_ascii=False, sort_keys=True)


def deserialize_context(text: str) -> dict:
    return json.loads(text)