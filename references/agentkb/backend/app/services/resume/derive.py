from datetime import UTC, date, datetime


def derive_years_experience(candidate: dict, reference_date: date | None = None) -> int | None:
    """Schema spec §1.8：仅合并 full_time 闭区间，整年向下取整。"""
    reference_date = reference_date or datetime.now(UTC).date()
    intervals: list[tuple[int, int]] = []
    for work in candidate.get("work") or []:
        if work.get("type") != "full_time" or not work.get("start"):
            continue
        try:
            sy, sm = map(int, work["start"].split("-"))
            end = work.get("end") or f"{reference_date.year:04d}-{reference_date.month:02d}"
            ey, em = map(int, end.split("-"))
            start_month, end_month = sy * 12 + sm, ey * 12 + em
        except (AttributeError, TypeError, ValueError):
            continue
        if end_month >= start_month:
            intervals.append((start_month, end_month))
    if not intervals:
        return None
    intervals.sort()
    merged: list[list[int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    months = sum(end - start + 1 for start, end in merged)
    return months // 12


def _valid_month(value: str) -> tuple[int, int] | None:
    try:
        y, m = map(int, value.split("-"))
    except (AttributeError, TypeError, ValueError):
        return None
    if not (1 <= m <= 12):
        return None
    return y, m


def detect_conflicts(candidate: dict) -> list[dict]:
    """P2 最小 conflict：时间线重叠 + 时间字段非法/缺失（spec §1.8），进入人工确认而不豁免评测。"""
    conflicts = []
    work = candidate.get("work") or []
    for i, entry in enumerate(work):
        start, end = entry.get("start"), entry.get("end")
        if start is None and end is not None:
            conflicts.append({
                "field": f"work[{i}].start",
                "type": "other",
                "values": [None, end],
                "evidence": f"work[{i}] 缺少开始时间",
                "reason": "工作经历缺少开始时间，无法计入工作年限",
            })
            continue
        if start is not None and end is not None:
            s, e = _valid_month(start), _valid_month(end)
            if s is None or e is None:
                continue  # 非法格式已在 Schema 校验阶段拒绝入库
            if e < s:
                conflicts.append({
                    "field": f"work[{i}].end",
                    "type": "value_conflict",
                    "values": [start, end],
                    "evidence": f"work[{i}] 结束时间早于开始时间",
                    "reason": "工作经历结束时间早于开始时间",
                })
    for i, left in enumerate(work):
        for j, right in enumerate(work[i + 1:], start=i + 1):
            if not all((left.get("start"), left.get("end"), right.get("start"), right.get("end"))):
                continue
            if left["start"] <= right["end"] and right["start"] <= left["end"]:
                conflicts.append({
                    "field": f"work[{i}].start",
                    "type": "timeline_overlap",
                    "values": [left["start"], right["start"]],
                    "evidence": f"work[{i}] 与 work[{j}] 时间段重叠",
                    "reason": "同一候选人工作经历时间线重叠",
                })
    return conflicts