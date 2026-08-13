# P9 人才库统计查询（F11）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [x]`）语法来跟踪进度。

**目标：** 落地 F11 统计查询意图——"人才库里有多少 Java 候选人？城市分布？" → 结构化统计卡片（数量 + 分布），与搜人同池范围 ACL（默认 active、与 `allowed_pool_scopes` 求交集、不可访问池不泄露），严格只读。

**架构：** 扩展 `extractor` 的 `statistics` 意图输出 `stat_group_by` 分布维度；新增统计聚合服务 `search/statistics.py`（纯 SQL 计数 + GROUP BY，复用 `build_condition_filter`/`requires_profile_join`，画像字段 JOIN latest_revision）；`flow.run_search_flow` 移除 statistics 拒答并新增 `_run_statistics` 分支；`SearchOutcome` 增 `statistics` 字段；`search_chat.py` 非流式响应与 SSE 透传统计卡片；前端 SearchPage 渲染统计卡片。

**技术栈：** FastAPI、SQLAlchemy 2.0（async）、pgvector、pydantic v2、pytest、React、vitest。

**参考：** `docs/PRD.md` §7.2 F11（严格只读 + 池范围规则）、搜人评测 spec v0.4 §2.2/§2.3/§3.7（统计准确率 ≥0.90、空桶按 0、不得返回不可访问池数量/分布）、P3 `extractor.py`/`flow.py`/`candidate_search.py`（池 ACL 与条件编译）。

---

## 设计决策与歧义裁决（实现前必读）

| # | 歧义 / 取舍 | 依据 | 本计划裁决 |
|---|------------|------|-----------|
| T-1 | 统计卡片结构 | 搜人评测 v0.4 §3.7「数量类 exact match；分布类按类别 macro accuracy」；PRD F11「结构化统计卡片（数量/分布）」 | `{"count": int, "dimension": str|null, "distribution": [{"key", "count"}, ...]}`；`dimension=null` 为纯计数（distribution 空数组）；`dimension` 非空时形如城市分布 `[{"key":"杭州","count":5},...]` |
| T-2 | 分布维度集合 | 复用搜人条件字段（`structured_data` + 画像字段），避免新字段 | `STAT_GROUP_BY = {city, expected_city, highest_degree, years_experience, expected_position, level, domain, management}`；画像字段（level/domain/management）需 JOIN latest_revision 读 `profile_json->'values'` |
| T-3 | 分布统计口径 | 搜人评测 v0.4 §2.2「去重键与池范围随 bundle 冻结」 | 统计按候选人行去重（`candidates.id` 唯一），`COUNT(*)` 即人数；分布 GROUP BY 维度表达式并按计数降序；空桶（未出现类别）不显式补 0（评测 scorer 侧按 0 参与计算，API 只返回出现过的桶） |
| T-4 | 池范围与 ACL | PRD F11「默认只查企业人才库；请求池范围先与 allowed_pool_scopes 求交集；不可访问池不泄露」 | 与 search/job_search 完全一致：`scopes = {pool_scope} ∩ allowed`，空则返回「无权限查询该人才池。」；统计结果、summary、审计 payload 均不含不可访问池信息 |
| T-5 | 统计意图是否要求 embedding | 统计为纯 SQL 聚合，无需向量/rerank | 不调用 embedder/rerank（仅 LLM 意图抽取），显著降本；`_run_statistics` 只依赖 `_get_llm` |
| T-6 | 多轮追问统计（"那城市分布呢？"） | 评测 spec §2.3 统计查询族为单轮；PRD 示例为单轮复合（"数量？城市分布？"） | MVP 统计为单轮意图：`stat_group_by` 由 LLM 在单次抽取中输出；follow_up 转统计的跨意图收敛记录为已接受后续项（V1.1） |
| T-7 | 统计上下文 | 后续轮询可复用条件 | `_run_statistics` 存 `context={"conditions", "pool_scope"}`（与 search 一致），statistics 本身不再写 context 之外的字段 |

---

## 文件结构

```
backend/
  app/services/search/
    extractor.py                                 (修改：statistics 意图输出 stat_group_by，校验+提示词)
    statistics.py                                (新：compute_statistics + STAT_GROUP_BY)
    flow.py                                      (修改：REFUSAL_INTENTS 移除 statistics、_run_statistics、SearchOutcome.statistics)
  app/api/
    search_chat.py                               (修改：非流式响应 + SSE 透传 statistics 事件)
  tests/
    test_search_extractor.py                     (修改：stat_group_by 校验用例)
    test_statistics.py                           (新：聚合服务 + flow 统计分支)
    test_search_chat_api.py                      (修改：API 级 statistics 断言)
  frontend/src/
    api/search.ts                                (修改：StatisticsCard 类型 + SSE 解析)
    pages/SearchPage.tsx                         (修改：渲染统计卡片)
    __tests__/search.test.ts                     (新：SSE statistics 事件解析)
```

**领域边界**：P9 不改条件编译/检索链路；`statistics` 意图不携带 `requested_count`/`job_id`（校验器已拒绝）；历史条件（如"曾拒绝 offer"）统计留 F15/M5 完整池流转。
---

### 任务 1：extractor 统计意图 stat_group_by

**文件：**
- 修改：`backend/app/services/search/extractor.py`
- 测试：`backend/tests/test_search_extractor.py`

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_search_extractor.py 追加
import pytest

from app.services.search.extractor import (
    SearchExtractionError,
    validate_intent_output,
)


def test_statistics_accepts_stat_group_by():
    validate_intent_output({"intent": "statistics", "requested_count": None, "pool_scope": "active",
                            "conditions": [], "stat_group_by": "city", "reason": "城市分布"})
    validate_intent_output({"intent": "statistics", "requested_count": None, "pool_scope": "active",
                            "conditions": [], "stat_group_by": None, "reason": "仅计数"})


def test_stat_group_by_rejected_outside_statistics():
    with pytest.raises(SearchExtractionError, match="stat_group_by"):
        validate_intent_output({"intent": "search", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "stat_group_by": "city", "reason": ""})


def test_statistics_rejects_unknown_dimension():
    with pytest.raises(SearchExtractionError, match="stat_group_by"):
        validate_intent_output({"intent": "statistics", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "stat_group_by": "salary", "reason": ""})


def test_statistics_rejects_requested_count():
    with pytest.raises(SearchExtractionError, match="requested_count"):
        validate_intent_output({"intent": "statistics", "requested_count": 5, "pool_scope": "active",
                                "conditions": [], "stat_group_by": None, "reason": ""})
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_search_extractor.py -v`
预期：FAIL（stat_group_by 相关用例报错）

- [x] **步骤 3：实现 stat_group_by 校验与字段**

`backend/app/services/search/extractor.py`：

```python
STAT_GROUP_BY = {"city", "expected_city", "highest_degree", "years_experience",
                 "expected_position", "level", "domain", "management"}
```

`SearchIntent` dataclass 增加字段（放在字段表末尾 `reason` 之后——`job_id`/`job_title`/`reason` 均为无默认值字段，插在它们之前会触发 `TypeError: non-default argument follows default argument`）：

```python
    stat_group_by: str | None = None
```

`validate_intent_output` 增加（`job_id/job_title` 校验之后）：

```python
    stat_group_by = raw.get("stat_group_by")
    if intent != "statistics":
        if stat_group_by is not None:
            raise SearchExtractionError("stat_group_by 仅统计意图可携带")
    elif stat_group_by is not None and stat_group_by not in STAT_GROUP_BY:
        raise SearchExtractionError(f"非法 stat_group_by: {stat_group_by}")
```

`extract_search_intent` 返回增加：`stat_group_by=raw.get("stat_group_by"),`

`SEARCH_SYSTEM_PROMPT` 更新：
- 意图枚举第 65 行：`- statistics: 统计查询（输出 stat_group_by 分布维度，null 为仅计数）`
- 输出说明行后追加规则 7：

```
7. statistics 意图输出 stat_group_by：分布维度（city/expected_city/highest_degree/years_experience/expected_position/level/domain/management）或 null（仅计数）；statistics 不携带 requested_count。
```

- 输出模板行追加 `"stat_group_by": "city"|null,`

- [x] **步骤 4：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_search_extractor.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/search/extractor.py backend/tests/test_search_extractor.py
git commit -m "feat: extract statistics intent with stat_group_by dimension (P9 F11)"
```

---

### 任务 2：统计聚合服务

**文件：**
- 创建：`backend/app/services/search/statistics.py`
- 测试：`backend/tests/test_statistics.py`

**验收（T-1/T-2/T-3/T-4）：** `compute_statistics` 返回 `{count, dimension, distribution}`；条件过滤、画像维度 JOIN、池过滤、空结果。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_statistics.py
import pytest

from app.models import (
    Candidate,
    CandidateRevision,
    CandidateStatus,
    User,
    Workspace,
)
from app.services.search.statistics import compute_statistics


async def _seed(db, ws_id, *, name, city=None, degree=None, years=None, level=None, status=CandidateStatus.active):
    cand = Candidate(workspace_id=ws_id, status=status, name=name,
                     structured_data={"skills": ["Java"] if name.startswith("J") else ["Vue"],
                                      "city": city, "highest_degree": degree, "years_experience": years},
                     search_text=f"{name} Java")
    db.add(cand)
    await db.flush()
    rev = CandidateRevision(candidate_id=cand.id, run_id=f"st-{id(cand)}", revision_id=f"st-{id(cand)}:r1",
                            candidate_json={"skills": ["Java"]}, evidence={},
                            profile_json={"values": {"level": level}, "evidence": {}})
    db.add(rev)
    await db.flush()
    cand.latest_revision_id = rev.id


@pytest.mark.asyncio
async def test_compute_statistics_count_and_city_distribution():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        owner = User(email="st-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="st-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州", degree="本科", years=5)
        await _seed(db, ws.id, name="Java2", city="杭州", degree="硕士", years=3)
        await _seed(db, ws.id, name="Java3", city="上海", degree="本科", years=8)
        await _seed(db, ws.id, name="Vue4", city="北京", degree="本科", years=2)
        await db.commit()

        conds = [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}]
        stats = await compute_statistics(db, workspace_id=ws.id, conditions=conds,
                                         scopes={"active"}, group_by="city")
        assert stats["count"] == 3
        assert stats["dimension"] == "city"
        by_city = {g["key"]: g["count"] for g in stats["distribution"]}
        assert by_city == {"杭州": 2, "上海": 1}


@pytest.mark.asyncio
async def test_compute_statistics_count_only_and_empty():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        owner = User(email="st2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="st2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州")
        await db.commit()

        stats = await compute_statistics(db, workspace_id=ws.id, conditions=[], scopes={"active"}, group_by=None)
        assert stats["count"] == 1
        assert stats["dimension"] is None
        assert stats["distribution"] == []

        stats_empty = await compute_statistics(db, workspace_id=ws.id, conditions=[], scopes={"active"}, group_by=None)
        # 池过滤：rejected 池无数据
        stats_rej = await compute_statistics(db, workspace_id=ws.id, conditions=[], scopes={"rejected"}, group_by=None)
        assert stats_rej["count"] == 0


@pytest.mark.asyncio
async def test_compute_statistics_profile_dimension_joins_revision():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        owner = User(email="st3-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="st3-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州", level="Mid")
        await _seed(db, ws.id, name="Java2", city="杭州", level="Senior")
        await db.commit()

        stats = await compute_statistics(db, workspace_id=ws.id, conditions=[], scopes={"active"}, group_by="level")
        by_level = {g["key"]: g["count"] for g in stats["distribution"]}
        assert by_level == {"Mid": 1, "Senior": 1}
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_statistics.py -v`
预期：FAIL（ModuleNotFoundError / 断言失败）

- [x] **步骤 3：实现 compute_statistics**

```python
# backend/app/services/search/statistics.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, CandidateRevision, CandidateStatus
from app.services.search.schema import (
    build_condition_filter,
    requires_profile_join,
    validate_conditions,
)

STAT_GROUP_BY = {"city", "expected_city", "highest_degree", "years_experience",
                 "expected_position", "level", "domain", "management"}
_PROFILE_DIMS = {"level", "domain", "management"}
_SEARCHABLE_STATUS = {"active", "rejected", "hired"}


def _dimension_expr(dim):
    if dim in _PROFILE_DIMS:
        return func.coalesce(CandidateRevision.profile_json["values"][dim].astext, "未知").label("dim_key")
    return func.coalesce(Candidate.structured_data.op("->>")(dim), "未知").label("dim_key")


async def compute_statistics(db: AsyncSession, *, workspace_id: int, conditions: list,
                             scopes: set[str], group_by: str | None) -> dict:
    """统计查询（T-1/T-2/T-3）：计数 + 分布。条件/画像复用搜人编译规则，池过滤与 ACL 由调用方保证。"""
    validate_conditions(conditions)
    statuses = [CandidateStatus(s) for s in scopes if s in _SEARCHABLE_STATUS]
    if not statuses:
        return {"count": 0, "dimension": group_by, "distribution": []}
    need_profile = requires_profile_join(conditions) or (group_by in _PROFILE_DIMS)
    cols = [Candidate.id]
    if group_by:
        cols.append(_dimension_expr(group_by))
    base = select(*cols).where(
        Candidate.workspace_id == workspace_id, Candidate.status.in_(statuses))
    if need_profile:
        base = base.join(CandidateRevision, CandidateRevision.id == Candidate.latest_revision_id)
    cond_expr = build_condition_filter(conditions)
    if cond_expr is not None:
        base = base.where(cond_expr)

    sub = base.subquery()
    count = (await db.execute(select(func.count()).select_from(sub))).scalar_one()
    distribution = []
    if group_by:
        rows = await db.execute(
            select(sub.c.dim_key, func.count().label("cnt"))
            .select_from(sub).group_by(sub.c.dim_key)
            .group_by(sub.c.dim_key)
            .order_by(func.count().desc()))
        distribution = [{"key": k, "count": c} for k, c in rows.all()]
    return {"count": count, "dimension": group_by, "distribution": distribution}
```

> 注：上述代码示例中的 `.group_by(sub.c.dim_key)` 只需一行（列表 `.group_by()` 只调用一次），实现时勿重复调用。

- [x] **步骤 4：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_statistics.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/search/statistics.py backend/tests/test_statistics.py
git commit -m "feat: add statistics aggregation service (P9 F11)"
```

---

### 任务 3：flow 统计分支

**文件：**
- 修改：`backend/app/services/search/flow.py`
- 测试：`backend/tests/test_statistics.py`（追加）

**验收（T-4/T-5/T-7）：** `statistics` 意图不再拒答；`_run_statistics` 池 ACL、summary、context、审计；`SearchOutcome.statistics` 透传。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_statistics.py 追加
from app.core.database import SessionLocal
from app.services.search.flow import run_search_flow


class FakeLLM:
    def __init__(self, intent="statistics", stat_group_by=None, conditions=None, pool_scope="active"):
        self._out = {"intent": intent, "requested_count": None, "pool_scope": pool_scope,
                     "conditions": conditions or [], "stat_group_by": stat_group_by,
                     "job_id": None, "job_title": None, "reason": ""}

    async def chat_json(self, system, user, schema):
        return self._out


def _patch(monkeypatch, llm):
    async def fake_get_llm(db, ws):
        return llm

    async def fake_get_embedder(db, ws):
        raise AssertionError("统计查询不应调用 embedder")

    async def fake_get_rerank(db, ws):
        raise AssertionError("统计查询不应调用 rerank")

    monkeypatch.setattr("app.services.search.flow._get_llm", fake_get_llm)
    monkeypatch.setattr("app.services.search.flow._get_embedder", fake_get_embedder)
    monkeypatch.setattr("app.services.search.flow._get_rerank", fake_get_rerank)


@pytest.mark.asyncio
async def test_statistics_flow_returns_card_with_distribution(monkeypatch):
    _patch(monkeypatch, FakeLLM(stat_group_by="city"))
    async with SessionLocal() as db:
        owner = User(email="stf-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="stf-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州")
        await _seed(db, ws.id, name="Java2", city="上海")
        await db.commit()
        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                        utterance="人才库里有多少 Java 候选人？城市分布？", prior_context=None)
        assert outcome.intent == "statistics"
        assert outcome.statistics is not None
        assert outcome.statistics["count"] == 2
        assert outcome.statistics["dimension"] == "city"
        assert {g["key"]: g["count"] for g in outcome.statistics["distribution"]} == {"杭州": 1, "上海": 1}
        assert "城市分布" in outcome.summary


@pytest.mark.asyncio
async def test_statistics_flow_count_only(monkeypatch):
    _patch(monkeypatch, FakeLLM(stat_group_by=None))
    async with SessionLocal() as db:
        owner = User(email="stf2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="stf2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州")
        await db.commit()
        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                        utterance="有多少 Java 候选人？", prior_context=None)
        assert outcome.intent == "statistics"
        assert outcome.statistics["count"] == 1
        assert outcome.statistics["dimension"] is None


@pytest.mark.asyncio
async def test_statistics_flow_pool_denied(monkeypatch):
    _patch(monkeypatch, FakeLLM(stat_group_by=None, pool_scope="hired"))
    async with SessionLocal() as db:
        owner = User(email="stf3-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="stf3-ws", owner_id=owner.id)
        db.add(ws)
        await db.commit()
        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                        utterance="入职员工库有多少人？", prior_context=None)
        assert outcome.intent == "statistics"
        assert outcome.statistics is None
        assert "无权限" in outcome.summary
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_statistics.py -v`
预期：FAIL（statistics 仍拒答 / SearchOutcome 无 statistics 字段）

- [x] **步骤 3：实现 flow 统计分支**

`backend/app/services/search/flow.py`：

```python
REFUSAL_INTENTS = {"write_request"}  # statistics 已落地（P9 F11）
```

`SearchOutcome` 增加字段：

```python
    statistics: dict | None = None
```

`_refusal_text` 删除 `"statistics"` 键。

`run_search_flow` 在 `if parsed.intent == "job_search":` 之前插入：

```python
    if parsed.intent == "statistics":
        return await _run_statistics(db, workspace_id=workspace_id, actor_role=actor_role,
                                     actor_id=actor_id, parsed=parsed, prior=prior)
```

新增 `_run_statistics`（放在 `_run_job_search` 之后）：

```python
DIMENSION_LABELS = {
    "city": "城市", "expected_city": "期望城市", "highest_degree": "学历",
    "years_experience": "年限", "expected_position": "期望岗位",
    "level": "职级", "domain": "领域", "management": "管理能力",
}


async def _run_statistics(db, *, workspace_id: int, actor_role: str, actor_id: int,
                          parsed, prior: dict) -> SearchOutcome:
    from app.services.search.statistics import compute_statistics

    pool_scope = parsed.pool_scope or prior.get("pool_scope") or "active"
    allowed = ALLOWED_SCOPES_BY_ROLE.get(actor_role, set())
    scopes = ({pool_scope} if pool_scope else allowed) & allowed
    if not scopes:
        await add_event(db, action="search.pool.denied", result="denied",
                        resource_type="search", workspace_id=workspace_id, actor_id=actor_id,
                        payload={"requested": pool_scope, "role": actor_role})
        await db.commit()
        return SearchOutcome(intent="statistics", cards=[], summary="无权限查询该人才池。", context=None)

    stats = await compute_statistics(db, workspace_id=workspace_id, conditions=parsed.conditions,
                                     scopes=scopes, group_by=parsed.stat_group_by)
    if stats["dimension"] and stats["distribution"]:
        label = DIMENSION_LABELS.get(stats["dimension"], stats["dimension"])
        parts = "、".join(f"{g['key']} {g['count']}" for g in stats["distribution"])
        summary = f"人才库中共有 {stats['count']} 位候选人符合条件。{label}分布：{parts}。"
    else:
        summary = f"人才库中共有 {stats['count']} 位候选人符合条件。"

    context = {"conditions": parsed.conditions, "pool_scope": pool_scope}
    await add_event(db, action="search.statistics.executed", result="success",
                    resource_type="search", workspace_id=workspace_id, actor_id=actor_id,
                    payload={"count": stats["count"], "dimension": stats["dimension"]})
    await db.commit()
    return SearchOutcome(intent="statistics", cards=[], summary=summary, context=context, statistics=stats)
```

- [x] **步骤 4：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_statistics.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/search/flow.py backend/tests/test_statistics.py
git commit -m "feat: route statistics intent in search flow (P9 F11)"
```

---

### 任务 4：API 透传 statistics 卡片

**文件：**
- 修改：`backend/app/api/search_chat.py`
- 测试：`backend/tests/test_search_chat_api.py`

**验收：** 非流式响应含 `statistics`；SSE 新增 `statistics` 事件。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_search_chat_api.py 追加
@pytest.mark.asyncio
async def test_search_chat_returns_statistics_card(monkeypatch):
    async def fake_run_search_flow(db, *, workspace_id, actor_role, actor_id, utterance, prior_context):
        from app.services.search.flow import SearchOutcome
        return SearchOutcome(intent="statistics", cards=[], summary="人才库中共有 2 位候选人符合条件。城市分布：杭州 1、上海 1。",
                             context=None,
                             statistics={"count": 2, "dimension": "city",
                                         "distribution": [{"key": "杭州", "count": 1}, {"key": "上海", "count": 1}]})

    monkeypatch.setattr("app.api.search_chat.run_search_flow", fake_run_search_flow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "stc@b.com", "password": "secret123", "nickname": "S"})
        token = (await c.post("/api/v1/auth/login", json={"email": "stc@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "STC-WS"}, headers=h)).json()["id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "人才库有多少 Java 候选人？城市分布？", "stream": False}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "statistics"
        assert body["statistics"]["count"] == 2
        assert body["statistics"]["dimension"] == "city"


@pytest.mark.asyncio
async def test_search_chat_streams_statistics_event(monkeypatch):
    async def fake_run_search_flow(db, *, workspace_id, actor_role, actor_id, utterance, prior_context):
        from app.services.search.flow import SearchOutcome
        return SearchOutcome(intent="statistics", cards=[], summary="共有 1 位。", context=None,
                             statistics={"count": 1, "dimension": None, "distribution": []})

    monkeypatch.setattr("app.api.search_chat.run_search_flow", fake_run_search_flow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "sts@b.com", "password": "secret123", "nickname": "S"})
        token = (await c.post("/api/v1/auth/login", json={"email": "sts@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "STS-WS"}, headers=h)).json()["id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "有多少人？", "stream": True}, headers=h)
        assert r.status_code == 200
        assert '"type": "statistics"' in r.text
        assert '"count": 1' in r.text
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_search_chat_api.py -v`
预期：FAIL（响应无 statistics 字段 / SSE 无 statistics 事件）

- [x] **步骤 3：实现 API 透传**

`backend/app/api/search_chat.py` 的 `_execute` 返回值增加：

```python
            "statistics": outcome.statistics,
```

非流式返回体增加：

```python
            "statistics": payload["statistics"],
```

`gen()` 中 `job_candidates` 事件之后增加：

```python
            if payload.get("statistics"):
                yield f"data: {json.dumps({'type': 'statistics', 'statistics': payload['statistics']})}\n\n"
```

- [x] **步骤 4：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_search_chat_api.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/api/search_chat.py backend/tests/test_search_chat_api.py
git commit -m "feat: expose statistics card in search-chat API and SSE (P9 F11)"
```

---

### 任务 5：前端统计卡片解析与渲染

**文件：**
- 修改：`frontend/src/api/search.ts`
- 修改：`frontend/src/pages/SearchPage.tsx`
- 创建：`frontend/src/__tests__/search.test.ts`

**验收：** `searchChat` 解析 `statistics` SSE 事件；SearchPage 渲染数量 + 分布。

- [x] **步骤 1：编写失败的测试**

```typescript
// frontend/src/__tests__/search.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { searchChat } from "../api/search";
import { useAuthStore } from "../stores/authStore";

describe("searchChat statistics", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("parses statistics event from SSE stream", async () => {
    useAuthStore.getState().logout();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"intent","intent":"statistics"}\n\n'));
        controller.enqueue(new TextEncoder().encode('data: {"type":"statistics","statistics":{"count":2,"dimension":"city","distribution":[{"key":"杭州","count":1},{"key":"上海","count":1}]}}\n\n'));
        controller.enqueue(new TextEncoder().encode('data: {"type":"summary","text":"共有 2 位。城市分布：杭州 1、上海 1。"}\n\n'));
        controller.enqueue(new TextEncoder().encode('data: {"type":"done","message_id":1,"conversation_id":9}\n\n'));
        controller.close();
      },
    });
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, body });
    const result = await searchChat(1, "有多少 Java 候选人？城市分布？");
    expect(result.intent).toBe("statistics");
    expect(result.statistics?.count).toBe(2);
    expect(result.statistics?.distribution).toEqual([{ key: "杭州", count: 1 }, { key: "上海", count: 1 }]);
    expect(result.summary).toContain("城市分布");
  });
});
```

- [x] **步骤 2：运行测试验证失败**

运行：`cd frontend && npx vitest run src/__tests__/search.test.ts`
预期：FAIL（`statistics` 未定义 / 未解析）

- [x] **步骤 3：实现 search.ts**

`frontend/src/api/search.ts` 增加类型与解析：

```typescript
export interface StatisticsCard {
  count: number;
  dimension: string | null;
  distribution: { key: string; count: number }[];
}
```

`SearchResult` 增加：`statistics?: StatisticsCard;`

`searchChat` 初始值 `result` 增加 `statistics: undefined`；循环内增加：

```typescript
      if (event.type === "statistics") result.statistics = event.statistics ?? undefined;
```

- [x] **步骤 4：实现 SearchPage.tsx 渲染**

`frontend/src/pages/SearchPage.tsx`：`Turn` 接口增加 `statistics?: { count: number; dimension: string | null; distribution: { key: string; count: number }[] }`；`send` 中 turn 对象增加 `statistics: result.statistics`；卡片渲染区（`t.cards.map` 之前）增加：

```tsx
            {t.statistics && (
              <div data-testid="statistics-card">
                <b>统计：</b>共 {t.statistics.count} 位
                {t.statistics.dimension && t.statistics.distribution.length > 0 && (
                  <ul>
                    {t.statistics.distribution.map((g) => (
                      <li key={g.key}>
                        {g.key}: {g.count}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
```

- [x] **步骤 5：构建与测试**

```bash
cd frontend && npx vitest run && npm run build
```

预期：全部通过

- [x] **步骤 6：Commit**

```bash
git add frontend/src/api/search.ts frontend/src/pages/SearchPage.tsx frontend/src/__tests__/search.test.ts
git commit -m "feat: render statistics card in search page (P9 F11)"
```

---

### 任务 6：回归验证与台账

- [x] **步骤 1：全量回归**

```bash
export MODEL_KEY_ENC_KEY="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
export JWT_SECRET="deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/agentkb"
../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests -q
```

预期：全量通过（main 254 + P9 新增多条）

- [x] **步骤 2：静态检查**

```bash
../.worktrees/p2-resume-parsing/.venv/bin/ruff check backend/app backend/tests && git diff --check
```

- [x] **步骤 3：更新台账**

在 `docs/superpowers/deviation-log.md` 追加 §17「P9 人才库统计查询（F11）实现与偏离」，记录 T-1~T-7 裁决与验证。

- [x] **步骤 4：勾选计划并提交**

```bash
git add -A && git commit -m "docs: 记录 P9 统计查询实现偏差与验证（P9 F11）"
```

---

## 自检

**1. 规格覆盖度：**

| 需求 | 对应任务 |
|------|---------|
| 统计查询意图识别（statistics） | 任务 1 |
| 数量 + 分布（结构化统计卡片） | 任务 2、3 |
| 池范围 ACL（默认 active、交集、不泄露） | 任务 3 |
| 严格只读（无写操作） | 任务 3（仅审计只读事件） |
| API 非流式 + SSE 透传 | 任务 4 |
| 前端统计卡片渲染 | 任务 5 |
| 评测 §3.7 统计准确率口径（数量 exact / 分布 macro） | 任务 2（T-1/T-3 数据结构对齐） |

**2. 占位符扫描：** 无 TODO/占位；`compute_statistics`/`_run_statistics`/`stat_group_by`/`statistics` 字段在任务 1-4 定义、跨任务引用一致；`DIMENSION_LABELS` 在任务 3 定义。

**3. 类型一致性：** `SearchOutcome` 新增 `statistics` 字段后，`test_search_chat_api.py` 中既有 `SearchOutcome(...)` 构造不受影响（默认 `None`）；任务 2 步骤 3 代码示例中的 `.group_by()` 只调用一次（勿重复），自检标注不再展开。

**已知边界（后续处理）：** 多轮追问统计（"那城市分布呢？"跨意图收敛）；统计标准答案 fixture 与评测 bundle 冻结（需下载 AI Studio 数据集）；历史条件统计（F15/M5 完整池流转）；统计卡片空桶补 0 展示（MVP 按出现桶返回，scorer 侧以 0 参与计算）。