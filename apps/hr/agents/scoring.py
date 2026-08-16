# coding=utf-8
"""
    @project: MaxKB
    @file： scoring.py
    @date：2026/8/17
    @desc: Screening Agent 服务端评分与建议动作派生（PRD-AGENT-RAG §6.3）。
           LLM 只输出评估事实，score/suggested_action 由本模块按版本化函数强制计算。
"""

# 维度白名单（服务端强制，§6.5）：白名单外维度剔除并写 run 警告
DIMENSION_WHITELIST = ("技能匹配", "经验相关性", "工作年限", "城市", "学历")
# 必评维度：缺失或无数证 → evidence_ok=False
_REQUIRED_DIMENSIONS = ("技能匹配", "经验相关性")
# evidence_ok 下限：至少两个维度有证据且最高 relevance ≥ 0.3
_MIN_EVIDENCE_DIMENSIONS = 2
_MIN_EVIDENCE_RELEVANCE = 0.3


def evidence_strength(evidence):
    """evidence_strength(d) = 0（无 evidence），否则 min(1.0, max(relevance) + 0.05×(evidence 数-1))。"""
    if not evidence:
        return 0.0
    best = 0.0
    for item in evidence:
        try:
            relevance = float(item.get("relevance", 0) or 0)
        except (TypeError, ValueError):
            relevance = 0.0
        best = max(best, relevance)
    return min(1.0, best + 0.05 * (len(evidence) - 1))


def _clamp_confidence(value):
    try:
        confidence = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def derive_decision(payload, hard_met, bands=None, score_version="v1"):
    """由评估事实派生建议动作；返回 decision dict（score_version 由调用方传入）。"""
    bands = bands or {}
    try:
        advance = int(bands.get("advance", 80))
        hold = int(bands.get("hold", 60))
    except (TypeError, ValueError):
        advance, hold = 80, 60

    dimensions = payload.get("dimensions") or []
    warnings = []
    valid = []
    for dimension in dimensions:
        name = dimension.get("name")
        if name not in DIMENSION_WHITELIST:
            warnings.append({"name": str(name), "reason": "not in whitelist"})
            continue
        confidence = _clamp_confidence(dimension.get("confidence"))
        strength = evidence_strength(dimension.get("evidence") or [])
        valid.append({
            "name": name,
            "verdict": dimension.get("verdict", ""),
            "confidence": confidence,
            "evidence_strength": round(strength, 3),
            "dimension_score": round(confidence * strength, 3),
            "evidence_count": len(dimension.get("evidence") or []),
        })
    if valid:
        score = round(100 * sum(item["dimension_score"] for item in valid) / len(valid))
    else:
        score = None

    with_evidence = {item["name"] for item in valid if item["evidence_count"] > 0}
    required_dims_ok = _REQUIRED_DIMENSIONS[0] in with_evidence and _REQUIRED_DIMENSIONS[1] in with_evidence
    evidence_ok = required_dims_ok and len(with_evidence) >= _MIN_EVIDENCE_DIMENSIONS and any(
        float(item.get("relevance", 0) or 0) >= _MIN_EVIDENCE_RELEVANCE
        for dimension in dimensions
        for item in (dimension.get("evidence") or [])
        if dimension.get("name") in DIMENSION_WHITELIST
    )

    if not hard_met:
        suggested_action = "DECLINE"
    elif score is not None and score >= advance and evidence_ok:
        suggested_action = "ADVANCE"
    elif score is not None and score < hold:
        suggested_action = "DECLINE"
    else:
        suggested_action = "HOLD"

    return {
        "score": score,
        "suggested_action": suggested_action,
        "hard_met": bool(hard_met),
        "evidence_ok": evidence_ok,
        "required_dims_ok": required_dims_ok,
        "score_version": score_version,
        "dimension_details": valid,
        "warnings": warnings,
    }
