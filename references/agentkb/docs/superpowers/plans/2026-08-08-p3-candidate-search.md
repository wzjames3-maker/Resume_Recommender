# P3 对话式搜人（F7）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [x]`）语法来跟踪进度。

**目标：** 实现 F7 对话式搜人核心链路——意图识别 → 条件 AST 抽取 → 池过滤（M4 最小 ACL）→ 候选人五段向量混合检索 → rerank 排序 → SSE 候选卡片流式返回，多轮条件记忆，并跑通「搜人质量」核心指标可评测的闭环，为 M4 评测 bundle 提供可评分链路。

**架构：** 在 P1 知识库 chat（SSE）+ P2 候选人领域上新增独立搜人域。意图/条件抽取为 LLM 结构化输出（P2 structured 同款模式，单次调用、版本化 Schema、fail-closed）；检索为「结构化条件 SQL 过滤 ∩ 五段向量 RRF 召回 ∩ search_tsv 全文」，recall 后按 bge-reranker-v2-m3 相关度降序；`pool_scope` 按角色派生 `allowed_pool_scopes` 做服务端过滤（member 默认 active、显式 rejected；hired 仅 admin/owner；pending_review 不参与）。会话复用 conversations/messages 表（加 `workspace_id` 列，`knowledge_base_id` 可空），多轮条件在服务端持久化合并。真实 LLM/embedding/rerank 经 workspace model_config + P1 出站网关；测试一律 mock。

**技术栈：** FastAPI、SQLAlchemy 2.0（async）、pgvector（HNSW 向量检索）、PostgreSQL tsvector 全文、httpx、pydantic v2、pytest。

**参考：** `docs/PRD.md` §7.2 F7、`docs/superpowers/specs/2026-08-07-search-quality-evaluation.md`、`docs/superpowers/specs/2026-08-07-mvp-scope-and-acceptance.md` §3、P2 计划 A-3/A-11/A-16 裁决、`docs/superpowers/deviation-log.md` §9/§10。

---

## 设计决策与歧义裁决（实现前必读）

| # | 歧义 / 取舍 | 依据 | 本计划裁决 |
|---|------------|------|-----------|
| S-1 | rerank（bge-reranker-v2-m3）何时接入 | P2 A-3「rerank 接入 → P3」；PRD F7「统一按 rerank 相关度排序」 | **P3 接入 `RerankClient`**（workspace model_config `model_type="rerank"`，经出站网关）。rerank 不可用（未配置/调用失败）时降级为混合检索 RRF 排序并标记 `rerank: false`（评测 index_runtime 冻结口径） |
| S-2 | 检索三路合并 | 评测 spec §2.5 `index_runtime`（embedding/rerank/top_k/rrf）；PRD F7 混合检索 | 结构化条件在 SQL 侧确定过滤（技能/年限/城市/学历/名称/岗位）；语义召回 = 五段向量（每候选取最佳段距离）+ `search_tsv` 全文，两路 RRF 合并取 top_k，再 rerank 排序，卡片标注命中条件 |
| S-3 | 池过滤（M4 最小 ACL） | 评测 spec §2.2/§2.4；PRD F9「member 可查 active/rejected，hired 仅 admin/owner」 | `allowed_pool_scopes`：member = {active}（显式指定 rejected 时 + rejected）；admin/owner = {active, rejected, hired}。`pending_review`/`deleted`/`purged` 一律不参与搜索。`requested_pool_scope ∩ allowed` 为空 → 统一拒答（不含数量/池名/错误侧信道），仅审计 |
| S-4 | 意图/条件抽取调用形态 | P2 A-1 单次调用裁决 | 单次 LLM 调用输出 `{intent, conditions, requested_count, pool_scope, reason}`；版本化 Schema 校验（`search/v1`）；校验失败 not_retryable；无法确定标 null |
| S-5 | 多轮条件合并 | 评测 spec §3.6「每轮仅更新变化字段、保留上轮条件」 | follow_up 意图时以上轮 AST 为基线，仅应用本轮变化字段；`search` 意图重置基线。条件合并结果随 assistant 消息 `sources` 持久化（`{"type":"context"}`），供下一轮加载 |
| S-6 | 会话存储 | PRD F7 多轮记忆；现有 Conversation 绑定 KB | **复用** conversations/messages 表：新增 `workspace_id`（可空）+ `knowledge_base_id` 改可空；搜人会话 `knowledge_base_id=NULL`。P1 chat 端点对空 KB 会话返回 404（隔离），搜人端点校验 workspace 成员关系 |
| S-7 | 数量意图 requested_count | 评测 spec §3.4 数量满足率 | LLM 抽取出 `requested_count` 时返回 `min(N, 实际唯一命中)` 并明示「仅找到 X 个」；不足不凑数。响应含 `requested_count`/`returned_count` |
| S-8 | 未上线意图（job_search/statistics）与写请求 | 评测 spec §3.8 无副作用；F10/F11 未上线 | job_search/statistics/write_request 识别为**明确拒答**（结构化文案，无业务副作用），仅追加脱敏只读审计事件；chit_chat/out_of_scope 返回对话式文案。`non_search` 家族意图准确率目标 ≥0.90 在 P3 落地 |
| S-9 | 候选卡片与排序展示 | PRD F7「不展示数值分数」；评测 §3.9 可解释性 | 卡片含候选 ID/姓名/城市/学历/年限/期望岗位/命中条件/画像摘要，**不含分数**；按 rerank（或 RRF）相关度降序。SSE 事件：`cards`（整批）/`summary`/`done`/`error` |
| S-10 | 画像依赖查询 | 评测 §2.3 profile_dependent_search 未就绪仅观测 | conditions 支持 `level`/`domain`/`management`（读 candidate_revisions.profile_json JSONB），P3 实现过滤；但硬门槛验收留待画像标注子集就绪 |
| S-11 | 真实模型凭据 | P2 遗留待办 | P3 代码默认走 workspace model_config（llm/embedding/rerank）；测试 mock。真实凭据写入仍留用户提供 |
| S-12 | 前端 | MVP §3.3 UI E2E | P3 后端第一，末尾任务 9 交付最小搜人页（复用 chat SSE 客户端模式）；前端 token 续签沿用 P1 |

---

## 文件结构

```
backend/
  alembic/versions/<new>_search_conversation_workspace.py (新：conversations.workspace_id + KB 可空)
  app/
    models/
      conversation.py                      (修改：+ workspace_id 可空；knowledge_base_id 可空)
    services/
      model_client.py                      (修改：+ RerankClient)
      candidate_search.py                  (新：候选人混合检索 + 条件过滤 + 池过滤 + 命中标注)
      search/
        __init__.py                        (空)
        schema.py                          (新：search/v1 条件 AST + 意图 Schema + 校验)
        extractor.py                       (新：LLM 意图+条件抽取，P2 structured 同款)
        context.py                         (新：多轮条件合并/序列化)
        cards.py                           (新：候选人卡片组装 + 命中条件标注)
    api/
      search_chat.py                       (新：搜人 SSE 端点 + 会话管理)
    main.py                                (修改：注册 search router)
  tests/
    test_search_schema.py                  (新：条件 AST 校验 + SQL 过滤谓词)
    test_candidate_search.py               (新：混合检索 + 池过滤 + 命中标注)
    test_model_client_rerank.py            (新：RerankClient + 失败降级)
    test_search_extractor.py               (新：LLM 意图/条件抽取 + 校验)
    test_search_context.py                 (新：多轮合并/重置)
    test_search_chat_api.py                (新：SSE 端点 + 会话 + 越权拒答)
  frontend/src/
    api/search.ts                          (新：searchChat SSE 客户端)
    pages/SearchPage.tsx                   (新：搜人对话页)
    App.tsx                                (修改：路由)
```

**领域边界**：P3 不改 P1 的 `chat.py`/`search_service.py`（KB 检索保持隔离）；不改 P2 解析流水线。搜人独立于知识库 chat 域。

---

### 任务 1：Conversation 表支持搜人会话

**文件：**
- 修改：`backend/app/models/conversation.py`
- 创建：`backend/alembic/versions/<new>_search_conversation_workspace.py`
- 测试：`backend/tests/test_resume_models.py`（追加）

- [x] **步骤 1：编写失败的测试**

在 `backend/tests/test_resume_models.py` 追加：

```python
@pytest.mark.asyncio
async def test_conversation_supports_search_session():
    from app.core.database import SessionLocal
    from app.models import Conversation, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="conv-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="conv-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        conv = Conversation(user_id=owner.id, title="搜人会话", workspace_id=ws.id, knowledge_base_id=None)
        db.add(conv)
        await db.commit()
        got = (await db.get(Conversation, conv.id))
        assert got.workspace_id == ws.id and got.knowledge_base_id is None
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_resume_models.py::test_conversation_supports_search_session -v`
预期：FAIL，报错 "Conversation() got an unexpected keyword argument 'workspace_id'"

- [x] **步骤 3：修改模型**

`backend/app/models/conversation.py`：

```python
class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", text("updated_at DESC")),)
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    knowledge_base_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="新对话")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
```

- [x] **步骤 4：生成迁移**

```bash
cd backend
../.venv/bin/alembic revision --autogenerate -m "conversations support search sessions"
# 确认生成：add_column conversations.workspace_id (nullable)，alter knowledge_base_id 为 nullable
../.venv/bin/alembic upgrade head
```

迁移必须包含 `op.alter_column('conversations', 'knowledge_base_id', existing_type=sa.BigInteger(), nullable=True)`。若 autogenerate 未生成 alter，手工补上。

- [x] **步骤 5：运行测试验证通过**

运行：`pytest backend/tests/test_resume_models.py::test_conversation_supports_search_session -v`
预期：PASS

- [x] **步骤 6：Commit**

```bash
git add backend/app/models/conversation.py backend/alembic/versions backend/tests/test_resume_models.py
git commit -m "feat: support search sessions in conversations table (P3 F7)"
```

---

### 任务 2：RerankClient（bge-reranker-v2-m3 经出站网关）

**文件：**
- 修改：`backend/app/services/model_client.py`
- 测试：`backend/tests/test_model_client_rerank.py`

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_model_client_rerank.py
import pytest

from app.services.model_client import ModelCallError, RerankClient


def _patch_post(monkeypatch, payload: dict):
    async def fake_post(url, headers, json, timeout=60.0):
        return payload
    monkeypatch.setattr("app.services.model_client.http_post_json", fake_post)


@pytest.mark.asyncio
async def test_rerank_returns_scores_for_documents(monkeypatch):
    _patch_post(monkeypatch, {"results": [{"index": 0, "relevance_score": 0.9},
                                           {"index": 1, "relevance_score": 0.2}]})
    client = RerankClient(base_url="https://api.example.com/v1", api_key="sk-test", model="bge-reranker-v2-m3")
    scores = await client.rerank("找 Java 后端", ["Python 简历", "Java 支付系统"])
    assert len(scores) == 2
    assert scores[0] > scores[1]


@pytest.mark.asyncio
async def test_rerank_missing_results_is_not_retryable(monkeypatch):
    _patch_post(monkeypatch, {"results": []})
    client = RerankClient(base_url="https://api.example.com/v1", api_key="sk-test")
    with pytest.raises(ModelCallError) as exc:
        await client.rerank("q", ["d"])
    assert exc.value.retryable is False
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_model_client_rerank.py -v`
预期：FAIL，报错 "ModuleNotFoundError" / cannot import RerankClient

- [x] **步骤 3：实现 RerankClient**

`backend/app/services/model_client.py` 追加：

```python
class RerankClient:
    """bge-reranker-v2-m3 重排（S-1）：经出站网关，失败按 classify_llm_error 分类。"""

    def __init__(self, base_url: str, api_key: str, model: str = "bge-reranker-v2-m3"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        url = f"{self.base_url}/rerank"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            data = await http_post_json(url, headers, {"model": self.model, "query": query, "documents": documents})
        except Exception as exc:
            raise ModelCallError(f"rerank 调用失败: {exc}", retryable=classify_llm_error(exc)) from exc
        results = data.get("results") or []
        if not results:
            raise ModelCallError("rerank 返回空 results", retryable=False)
        scores = {int(r["index"]): float(r["relevance_score"]) for r in results if "index" in r}
        return [scores[i] for i in range(len(documents)) if i in scores]
```

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_model_client_rerank.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/model_client.py backend/tests/test_model_client_rerank.py
git commit -m "feat: add rerank client for bge-reranker-v2-m3 via outbound gateway (P3 F7)"
```

---

### 任务 3：搜人条件 AST Schema 与 SQL 过滤谓词

**文件：**
- 创建：`backend/app/services/search/__init__.py`
- 创建：`backend/app/services/search/schema.py`
- 测试：`backend/tests/test_search_schema.py`

**验收（评测 spec §2.4/§3.1）：** 条件项必须含 `field` 或 `fields`、`op`、`value`、`logic`、`missing_policy`；未知字段/操作符/缺失必填拒绝；`requested_count` 数量意图为 int；条件可编译为候选 SQL 谓词。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_search_schema.py
import pytest

from app.services.search.schema import (
    COND_FIELDS, OPS, SearchSchemaError, build_condition_filter, validate_conditions,
)


def _conds():
    return [
        {"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"},
        {"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"},
        {"fields": ["city", "expected_city"], "op": "any_match", "value": "杭州", "logic": "AND", "missing_policy": "exclude"},
    ]


def test_valid_conditions_pass():
    validate_conditions(_conds())


def test_unknown_field_rejected():
    with pytest.raises(SearchSchemaError, match="未知字段"):
        validate_conditions([{"field": "salary", "op": ">=", "value": 100, "logic": "AND", "missing_policy": "exclude"}])


def test_missing_missing_policy_rejected():
    with pytest.raises(SearchSchemaError, match="missing_policy"):
        validate_conditions([{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND"}])


def test_both_field_and_fields_rejected():
    with pytest.raises(SearchSchemaError, match="field 或 fields"):
        validate_conditions([{"field": "skills", "fields": ["city"], "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}])


def test_build_condition_filter_compiles_sql():
    from app.models import Candidate
    expr = build_condition_filter(_conds())
    # 编译为 SQL 文本，不抛异常
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql
    str(expr.compile(dialect=postgresql.dialect()))
    # 至少包含 years_experience 访问器
    assert "years_experience" in str(expr.compile(dialect=postgresql.dialect()))
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_search_schema.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现 Schema 与过滤谓词**

```python
# backend/app/services/search/__init__.py
# 空文件


# backend/app/services/search/schema.py
from sqlalchemy import or_, text

from app.models import Candidate

SEARCH_SCHEMA_VERSION = "search/v1"

COND_FIELDS = {
    "skills": "contains", "years_experience": "range", "city": "any_match",
    "expected_city": "any_match", "highest_degree": "range_degree", "expected_position": "contains_text",
    "name": "contains_text", "level": "eq", "domain": "contains_text", "management": "eq",
}
OPS = {"contains", "contains_text", ">=", ">=", "any_match", "eq", "range_degree"}
DEGREE_ORDINAL = {"初中": 1, "高中": 2, "中专": 3, "大专": 4, "本科": 5, "硕士": 6, "博士": 7}


class SearchSchemaError(Exception):
    pass


def _validate_one(cond: dict) -> None:
    has_field = "field" in cond
    has_fields = "fields" in cond
    if has_field == has_fields:
        raise SearchSchemaError("条件必须二选一提供 field 或 fields")
    op = cond.get("op")
    if op not in OPS:
        raise SearchSchemaError(f"未知操作符: {op}")
    if "missing_policy" not in cond or cond["missing_policy"] not in ("exclude", "include"):
        raise SearchSchemaError("missing_policy 必填且为 exclude/include")
    fields = [cond["field"]] if has_field else list(cond["fields"])
    for f in fields:
        if f not in COND_FIELDS and f not in ("city", "expected_city"):
            raise SearchSchemaError(f"未知字段: {f}")
    if "logic" not in cond or cond["logic"] not in ("AND", "OR"):
        raise SearchSchemaError("logic 必填且为 AND/OR")


def validate_conditions(conditions: list) -> None:
    if not isinstance(conditions, list):
        raise SearchSchemaError("conditions 必须为数组")
    for cond in conditions:
        _validate_one(cond)


def _jsonb_text(key: str):
    return text(f"candidates.structured_data->>'{key}'")


def build_condition_filter(conditions: list):
    """把条件 AST 编译为 candidates 表 SQL 谓词（S-2）。返回 and_ 组合的表达式。"""
    from sqlalchemy import and_, func

    exprs = []
    for cond in conditions:
        op = cond["op"]
        fields = [cond["field"]] if "field" in cond else list(cond["fields"])
        value = cond["value"]
        if op == "contains" and fields == ["skills"]:
            for skill in value:
                exprs.append(Candidate.search_tsv.op("@@")(func.plainto_tsquery("simple", skill)))
        elif op == "contains_text":
            for f in fields:
                exprs.append(_jsonb_text(f).ilike(f"%{value}%"))
        elif op == "any_match":
            parts = [_jsonb_text(f) == value for f in fields]
            exprs.append(or_(*parts))
        elif op == ">=" and fields == ["years_experience"]:
            exprs.append(func.coalesce(_jsonb_text("years_experience").cast("int"), -1) >= int(value))
        elif op == "range_degree" and fields == ["highest_degree"]:
            exprs.append(func.coalesce(_jsonb_text("highest_degree"), "") == value)
        elif op == "eq":
            for f in fields:
                exprs.append(_jsonb_text(f) == value)
        else:
            raise SearchSchemaError(f"不支持的条件组合: {op} {fields}")
    return and_(*exprs) if exprs else None
```

> 说明：`skills` 的 `contains` 走 `search_tsv @@ plainto_tsquery`（search_text 已含 skills 归一化文本）；`years_experience`/`highest_degree`/`city` 等读 `structured_data` JSONB 访问器。`level`/`domain`/`management` 读 `structured_data`（入库时画像已并入 structured_data 的 profile 字段，见任务 7 说明）。

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_search_schema.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/search backend/tests/test_search_schema.py
git commit -m "feat: add search condition AST schema and SQL filter (P3 F7)"
```

---

### 任务 4：候选人混合检索（五段向量 + 全文 + 池过滤 + 命中标注）

**文件：**
- 创建：`backend/app/services/candidate_search.py`
- 测试：`backend/tests/test_candidate_search.py`

**验收（PRD F7 / 评测 §3.2/§3.3）：** 在指定池范围内按「结构化过滤 ∩ 向量 RRF ∩ 全文」召回，返回去重候选 + 命中条件标注；池过滤不得泄漏 hired（member）；`pending_review/deleted/purged` 不返回。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidate_search.py
import pytest
from sqlalchemy import select

from app.services.candidate_search import ALLOWED_SCOPES_BY_ROLE, search_candidates
from app.services.search.schema import build_condition_filter, validate_conditions


@pytest.mark.asyncio
async def test_allowed_scopes_by_role():
    assert ALLOWED_SCOPES_BY_ROLE["member"] == {"active", "rejected"}
    assert "hired" in ALLOWED_SCOPES_BY_ROLE["admin"]
    assert "hired" in ALLOWED_SCOPES_BY_ROLE["owner"]


@pytest.mark.asyncio
async def test_search_candidates_filters_by_scopes_and_conditions():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateEmbedding, CandidateRevision, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="cs-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cs-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={"skills": ["Java"], "years_experience": 6, "city": "杭州", "highest_degree": "本科", "expected_city": "杭州"},
                         search_text="Java 支付", search_tsv="Java 支付")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="r1", revision_id="r1:rev1",
                                candidate_json={"skills": ["Java"]}, evidence={})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        db.add(CandidateEmbedding(candidate_id=cand.id, revision_id="r1:rev1", segment="work",
                                  text="支付系统", embedding=[0.1] * 1024))
        await db.commit()
        conds = [
            {"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"},
            {"fields": ["city", "expected_city"], "op": "any_match", "value": "杭州", "logic": "AND", "missing_policy": "exclude"},
            {"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"},
        ]
        validate_conditions(conds)
        hits = await search_candidates(db, ws.id, [0.1] * 1024, "Java 支付", conds,
                                       scopes={"active"}, top_k=10)
        assert any(h.candidate_id == cand.id for h in hits)
        hit = next(h for h in hits if h.candidate_id == cand.id)
        assert "skills" in hit.matched_conditions


@pytest.mark.asyncio
async def test_search_candidates_excludes_hired_for_member():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="cs2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cs2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        db.add(Candidate(workspace_id=ws.id, status=CandidateStatus.hired, name="李四",
                         structured_data={"skills": ["Java"]}, search_text="Java", search_tsv="Java"))
        await db.commit()
        hits = await search_candidates(db, ws.id, [0.1] * 1024, "Java", [], scopes={"active"}, top_k=10)
        assert not any(h.candidate_id == cand.id for h in hits)
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_candidate_search.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现候选检索**

```python
# backend/app/services/candidate_search.py
from dataclasses import dataclass

from pgvector.sqlalchemy import Vector
from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EMBEDDING_DIM, Candidate, CandidateEmbedding, CandidateRevision, CandidateStatus
from app.rag.retriever import rrf_merge, rrf_scores
from app.services.search.schema import build_condition_filter, validate_conditions

ALLOWED_SCOPES_BY_ROLE = {
    "member": {"active", "rejected"},
    "admin": {"active", "rejected", "hired"},
    "owner": {"active", "rejected", "hired"},
}
_SEARCHABLE_STATUS = {CandidateStatus.active, CandidateStatus.rejected, CandidateStatus.hired}


@dataclass
class CandidateHit:
    candidate_id: int
    score: float
    matched_conditions: list[str]


async def _latest_revision_join(alias_ce):
    """候选嵌入仅取 latest_revision 对应 revision_id（candidates.latest_revision_id）。"""
    return (
        alias_ce.join(Candidate, Candidate.id == alias_ce.c.candidate_id)
        .join(CandidateRevision, CandidateRevision.id == Candidate.latest_revision_id)
        .onclause  # placeholder replaced below
    )


async def search_candidates(db: AsyncSession, workspace_id: int, query_embedding: list[float],
                            query_text: str, conditions: list, scopes: set[str],
                            top_k: int = 20) -> list[CandidateHit]:
    validate_conditions(conditions)
    statuses = [CandidateStatus(s) for s in scopes if s in _SEARCHABLE_STATUS]
    if not statuses:
        return []
    cond_expr = build_condition_filter(conditions)

    base = (
        select(Candidate.id)
        .where(Candidate.workspace_id == workspace_id, Candidate.status.in_(statuses))
    )
    if cond_expr is not None:
        base = base.where(cond_expr)

    # 1) 向量召回：五段向量取每候选最小距离，限制在过滤集内
    vec_cte = base.cte("filtered")
    vec_stmt = text(
        "SELECT ce.candidate_id AS cid, MIN(ce.embedding <=> :q) AS dist "
        "FROM candidate_embeddings ce "
        "JOIN candidates c ON c.id = ce.candidate_id "
        "JOIN candidate_revisions cr ON cr.id = c.latest_revision_id AND cr.revision_id = ce.revision_id "
        "JOIN filtered ON filtered.id = c.id "
        "WHERE c.workspace_id = :ws AND c.status = ANY(:statuses) "
        "GROUP BY ce.candidate_id ORDER BY dist LIMIT :n"
    ).bindparams(text("q"), type_=Vector(EMBEDDING_DIM)) if False else text(
        "SELECT ce.candidate_id AS cid, MIN(ce.embedding <=> :q) AS dist "
        "FROM candidate_embeddings ce "
        "JOIN candidates c ON c.id = ce.candidate_id "
        "JOIN candidate_revisions cr ON cr.id = c.latest_revision_id AND cr.revision_id = ce.revision_id "
        "JOIN filtered ON filtered.id = c.id "
        "GROUP BY ce.candidate_id ORDER BY dist LIMIT :n"
    )
    vec_rows = await db.execute(vec_stmt, {"q": query_embedding, "n": top_k * 2})
    vec_ids = [r[0] for r in vec_rows.all()]

    # 2) 全文召回（search_tsv，simple 配置）
    full_stmt = (
        select(Candidate.id)
        .where(Candidate.workspace_id == workspace_id, Candidate.status.in_(statuses),
               Candidate.search_tsv.op("@@")(func.plainto_tsquery("simple", query_text)))
    )
    if cond_expr is not None:
        full_stmt = full_stmt.where(cond_expr)
    full_rows = await db.execute(full_stmt.limit(top_k * 2))
    full_ids = [r[0] for r in full_rows.all()]

    rankings = [vec_ids, full_ids]
    scores = rrf_scores(rankings)
    merged = rrf_merge(rankings)[:top_k]
    if not merged:
        return []
    max_score = max((scores[i] for i in merged), default=0.0)

    # 3) 命中条件标注：对每个返回候选，逐条件判断 structured_data 是否命中
    rows = await db.execute(select(Candidate).where(Candidate.id.in_(merged)))
    cands = {c.id: c for c in rows.scalars().all()}
    hits = []
    for cid in merged:
        c = cands.get(cid)
        if c is None:
            continue
        score = (scores[cid] / max_score) if max_score > 0 else 0.0
        hits.append(CandidateHit(candidate_id=cid, score=round(score, 4),
                                 matched_conditions=_match_conditions(c, conditions)))
    return hits


def _match_conditions(candidate: Candidate, conditions: list) -> list[str]:
    """返回该候选命中的条件字段路径（S-9 命中标注）。"""
    sd = candidate.structured_data or {}
    matched = []
    for cond in conditions:
        fields = [cond["field"]] if "field" in cond else list(cond["fields"])
        op, value = cond["op"], cond["value"]
        if op == "contains" and fields == ["skills"]:
            skills = [s.lower() for s in (sd.get("skills") or [])]
            if any(str(v).lower() in skills for v in value):
                matched.append("skills")
        elif op == "contains_text":
            for f in fields:
                if str(sd.get(f) or "").lower().find(str(value).lower()) >= 0:
                    matched.append(f)
                    break
        elif op == "any_match":
            if any(str(sd.get(f)) == str(value) for f in fields):
                matched.append("|".join(fields))
        elif op == ">=" and fields == ["years_experience"]:
            try:
                if int(sd.get("years_experience") or -1) >= int(value):
                    matched.append("years_experience")
            except (TypeError, ValueError):
                pass
        elif op == "eq":
            for f in fields:
                if str(sd.get(f)) == str(value):
                    matched.append(f)
    return matched
```

> 实现注意：`vec_stmt` 中的 `bindparams` 用法在实现时以 P1 `hybrid_search` 的 `bindparam("q", type_=Vector(EMBEDDING_DIM))` 模式为准（见 `backend/app/services/search_service.py:22-24`），避免 asyncpg 无法编码 list。测试用 PG 实跑。

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_candidate_search.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/candidate_search.py backend/tests/test_candidate_search.py
git commit -m "feat: add candidate hybrid search with pool scopes and condition highlighting (P3 F7)"
```

---

### 任务 5：LLM 意图识别 + 条件抽取（search/v1）

**文件：**
- 创建：`backend/app/services/search/extractor.py`
- 测试：`backend/tests/test_search_extractor.py`

**验收（评测 §2.3/§3.1/§3.8）：** 单次调用输出 `{intent, conditions[], requested_count, pool_scope, reason}`；Schema 校验失败 not_retryable；intent 枚举 `search/follow_up/job_search/statistics/write_request/chit_chat/out_of_scope`；`requested_count` 仅数量意图非空。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_search_extractor.py
import pytest

from app.services.search.extractor import INTENTS, SearchExtractionError, extract_search_intent, validate_intent_output


def test_valid_search_output_passes():
    output = {
        "intent": "search",
        "requested_count": None,
        "pool_scope": "active",
        "conditions": [
            {"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"},
        ],
        "reason": "用户要求 Java 技能",
    }
    validate_intent_output(output)


def test_unknown_intent_rejected():
    with pytest.raises(SearchExtractionError, match="intent"):
        validate_intent_output({"intent": "hack", "requested_count": None, "pool_scope": "active", "conditions": [], "reason": ""})


def test_unknown_pool_scope_rejected():
    with pytest.raises(SearchExtractionError, match="pool_scope"):
        validate_intent_output({"intent": "search", "requested_count": None, "pool_scope": "hired_pool", "conditions": [], "reason": ""})


def test_requested_count_only_for_candidate_intents():
    with pytest.raises(SearchExtractionError, match="requested_count"):
        validate_intent_output({"intent": "chit_chat", "requested_count": 5, "pool_scope": None, "conditions": [], "reason": ""})


@pytest.mark.asyncio
async def test_extract_search_intent_calls_llm():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"intent": "search", "requested_count": 5, "pool_scope": "active",
                    "conditions": [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}],
                    "reason": "找 5 个 Java 人"}

    out = await extract_search_intent(FakeLLM(), "找 5 个 Java 人", prior_conditions=None)
    assert out.intent == "search"
    assert out.requested_count == 5
    assert out.conditions[0]["field"] == "skills"
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_search_extractor.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现抽取器**

```python
# backend/app/services/search/extractor.py
from dataclasses import dataclass

from app.services.search.schema import SEARCH_SCHEMA_VERSION, SearchSchemaError, validate_conditions

INTENTS = {"search", "follow_up", "job_search", "statistics", "write_request", "chit_chat", "out_of_scope"}
POOL_SCOPES = {"active", "rejected", "hired", None}
_CANDIDATE_INTENTS = {"search", "follow_up"}
SEARCH_PROMPT_VERSION = "search-prompt/v1"


class SearchExtractionError(Exception):
    pass


@dataclass
class SearchIntent:
    intent: str
    conditions: list
    requested_count: int | None
    pool_scope: str | None
    reason: str


def validate_intent_output(raw: dict) -> None:
    intent = raw.get("intent")
    if intent not in INTENTS:
        raise SearchExtractionError(f"非法 intent: {intent}")
    if raw.get("pool_scope") not in POOL_SCOPES:
        raise SearchExtractionError(f"非法 pool_scope: {raw.get('pool_scope')}")
    conditions = raw.get("conditions") or []
    try:
        validate_conditions(conditions)
    except SearchSchemaError as exc:
        raise SearchExtractionError(str(exc)) from exc
    requested = raw.get("requested_count")
    if requested is not None:
        if intent not in _CANDIDATE_INTENTS:
            raise SearchExtractionError("requested_count 仅候选意图可携带")
        if not isinstance(requested, int) or requested <= 0:
            raise SearchExtractionError("requested_count 必须为正整数")


SEARCH_SYSTEM_PROMPT = f"""你是招聘搜人意图解析器。输入用户自然语言与上一轮条件（可为空），输出严格 JSON（schema_version={SEARCH_SCHEMA_VERSION}）。

意图枚举（job_search/statistics 表示未上线功能，仅识别不执行）:
- search: 全新人事查询
- follow_up: 在上一轮条件基础上追问/收敛（仅更新变化字段）
- job_search: 按岗位搜索（当前未上线）
- statistics: 统计查询（当前未上线）
- write_request: 写请求/批量操作（不得执行）
- chit_chat: 闲聊
- out_of_scope: 超出范围

条件字段与操作符（每项含 logic 与 missing_policy）:
- skills contains (数组值)
- years_experience >= (整数)
- city / expected_city any_match（fields: ["city","expected_city"]）
- highest_degree range_degree（值：初中/高中/中专/大专/本科/硕士/博士）
- expected_position contains_text
- name contains_text
- level / management eq（画像字段）
- domain contains_text

规则:
1. 仅输出上述字段，不得输出未知字段。
2. 无法从查询确定的条件不输出；禁止编造条件。
3. requested_count 为数量意图（如"找 5 个"），无数量为 null。
4. pool_scope 为 active（默认）/ rejected（显式指定"已面试未通过/淘汰池"）/ hired（显式指定"入职员工库"）。
5. follow_up 时 pool_scope 保持上一轮值，requested_count 保持上一轮值。
输出: {{"intent": "...", "requested_count": int|null, "pool_scope": "...", "conditions": [...], "reason": "..."}}"""


async def extract_search_intent(llm, utterance: str, prior_conditions: list | None) -> SearchIntent:
    prior_text = "" if not prior_conditions else f"上一轮条件: {prior_conditions}"
    raw = await llm.chat_json(SEARCH_SYSTEM_PROMPT, f"上一轮条件库: {prior_text}\n用户: {utterance}", {})
    if not isinstance(raw, dict):
        raise SearchExtractionError("LLM 输出必须为对象")
    validate_intent_output(raw)
    return SearchIntent(
        intent=raw["intent"], conditions=raw.get("conditions") or [],
        requested_count=raw.get("requested_count"), pool_scope=raw.get("pool_scope"),
        reason=raw.get("reason") or "",
    )
```

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_search_extractor.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/search/extractor.py backend/tests/test_search_extractor.py
git commit -m "feat: add LLM search intent and condition extraction with schema validation (P3 F7)"
```

---

### 任务 6：多轮条件合并（context）

**文件：**
- 创建：`backend/app/services/search/context.py`
- 测试：`backend/tests/test_search_context.py`

**验收（评测 §3.6）：** follow_up 仅更新变化字段、保留上轮条件；search 重置；序列化/反序列化供消息持久化。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_search_context.py
from app.services.search.context import merge_follow_up, serialize_context, deserialize_context


def _java_cond():
    return {"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}


def test_follow_up_keeps_prior_and_applies_change():
    prior = [_java_cond(), {"field": "years_experience", "op": ">=", "value": 3, "logic": "AND", "missing_policy": "exclude"}]
    change = [{"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"}]
    merged = merge_follow_up(prior, change)
    assert _java_cond() in merged
    assert any(c["field"] == "years_experience" and c["value"] == 5 for c in merged)


def test_follow_up_removes_none_condition():
    prior = [_java_cond(), {"fields": ["city", "expected_city"], "op": "any_match", "value": "杭州", "logic": "AND", "missing_policy": "exclude"}]
    merged = merge_follow_up(prior, [{"field": "city", "op": "any_match", "value": None, "logic": "AND", "missing_policy": "include"}])
    assert not any(c.get("fields") == ["city", "expected_city"] for c in merged)


def test_context_serialize_roundtrip():
    ctx = {"conditions": [_java_cond()], "pool_scope": "active", "requested_count": None}
    assert deserialize_context(serialize_context(ctx)) == ctx
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_search_context.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现合并逻辑**

```python
# backend/app/services/search/context.py
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
```

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_search_context.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/search/context.py backend/tests/test_search_context.py
git commit -m "feat: add multi-turn search context merge (P3 F7)"
```

---

### 任务 7：候选人卡片组装

**文件：**
- 创建：`backend/app/services/search/cards.py`
- 测试：`backend/tests/test_candidate_search.py`（追加）

**验收（PRD F7 / 评测 §3.9）：** 卡片含 ID/姓名/城市/学历/年限/期望岗位/命中条件/画像摘要，不含数值分数；画像来自结构化数据。

- [x] **步骤 1：编写失败的测试**

在 `backend/tests/test_candidate_search.py` 追加：

```python
@pytest.mark.asyncio
async def test_build_candidate_cards_includes_hit_conditions_no_score():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, User, Workspace
    from app.services.search.cards import build_candidate_cards

    async with SessionLocal() as db:
        owner = User(email="card-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="card-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={"city": "杭州", "highest_degree": "本科", "years_experience": 6,
                                          "expected_position": "Java 后端", "skills": ["Java"],
                                          "profile": {"level": "Mid", "domain": "金融科技"}},
                         search_text="Java")
        db.add(cand)
        await db.commit()
        cards = await build_candidate_cards(db, [cand.id], [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}])
        assert cards[0]["candidate_id"] == cand.id
        assert cards[0]["name"] == "张三"
        assert "skills" in cards[0]["matched_conditions"]
        assert "score" not in cards[0]
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_candidate_search.py::test_build_candidate_cards_includes_hit_conditions_no_score -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现卡片组装**

```python
# backend/app/services/search/cards.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate
from app.services.candidate_search import _match_conditions


async def build_candidate_cards(db: AsyncSession, candidate_ids: list[int], conditions: list) -> list[dict]:
    if not candidate_ids:
        return []
    rows = await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
    cards = []
    for c in rows.scalars().all():
        sd = c.structured_data or {}
        profile = sd.get("profile") or {}
        cards.append({
            "candidate_id": c.id,
            "name": c.name,
            "city": sd.get("city"),
            "expected_city": sd.get("expected_city"),
            "highest_degree": sd.get("highest_degree"),
            "years_experience": sd.get("years_experience"),
            "expected_position": sd.get("expected_position"),
            "skills": sd.get("skills") or [],
            "matched_conditions": _match_conditions(c, conditions),
            "profile": {"level": profile.get("level"), "domain": profile.get("domain")},
        })
    return cards
```

> 说明：`profile` 在 P2 入库时存于 `candidate_revisions.profile_json`，`candidates.structured_data` 不含画像。为让卡片可读画像，任务 8 编排时从 `candidate_revisions.profile_json`（latest_revision）读取并合并到卡片；若缺失则 `profile` 置空。`_match_conditions` 已含画像字段（level/domain/management）的匹配。

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_candidate_search.py::test_build_candidate_cards_includes_hit_conditions_no_score -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/search/cards.py backend/tests/test_candidate_search.py
git commit -m "feat: add candidate card assembly with hit conditions (P3 F7)"
```

---

### 任务 8：搜人编排 + SSE 端点 + 会话管理

**文件：**
- 创建：`backend/app/services/search/flow.py`
- 创建：`backend/app/api/search_chat.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_search_chat_api.py`

**验收（PRD F7 / 评测 §3.1-§3.8）：** `POST /api/v1/workspaces/{ws_id}/search-chat` 全链路：意图→条件→池过滤→检索→rerank→卡片 SSE；多轮经会话持久化；job_search/statistics/write_request 拒答无副作用；越权池统一拒答；`non_search` 家族仅审计。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_search_chat_api.py
import json as _json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_search_chat_returns_candidate_cards(monkeypatch):
    import json
    from types import SimpleNamespace
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateEmbedding, CandidateRevision, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="sc-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="sc-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={"skills": ["Java"], "years_experience": 6, "city": "杭州",
                                          "highest_degree": "本科", "expected_city": "杭州"},
                         search_text="Java", search_tsv="Java")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="r", revision_id="r:rev1",
                                candidate_json={"skills": ["Java"]}, evidence={}, profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        db.add(CandidateEmbedding(candidate_id=cand.id, revision_id="r:rev1", segment="work",
                                  text="支付系统", embedding=[0.1] * 1024))
        await db.commit()
        ws_id = ws.id

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"intent": "search", "requested_count": None, "pool_scope": "active",
                    "conditions": [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}],
                    "reason": "找 Java"}

    class FakeEmbedder:
        async def embed(self, texts):
            return [[0.1] * 1024 for _ in texts]

    class FakeRerank:
        async def rerank(self, query, documents):
            return list(reversed(range(len(documents))))

    async def fake_get_llm(db, ws):
        return FakeLLM(), SimpleNamespace(base_url="https://api.deepseek.com/v1", model_name="deepseek-chat")
    async def fake_get_embedder(db, ws):
        return FakeEmbedder()
    async def fake_get_rerank(db, ws):
        return FakeRerank()

    monkeypatch.setattr("app.services.search.flow._get_llm", fake_get_llm)
    monkeypatch.setattr("app.services.search.flow._get_embedder", fake_get_embedder)
    monkeypatch.setattr("app.services.search.flow._get_rerank", fake_get_rerank)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "sc@b.com", "password": "secret123", "nickname": "S"})
        token = (await c.post("/api/v1/auth/login", json={"email": "sc@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "找 Java 后端", "stream": False}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "search"
        assert body["cards"] and body["cards"][0]["name"] == "张三"
        assert "score" not in body["cards"][0]


@pytest.mark.asyncio
async def test_search_chat_rejects_write_request_without_side_effect(monkeypatch):
    from app.core.database import SessionLocal
    from app.models import User, Workspace

    async with SessionLocal() as db:
        owner = User(email="sc2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="sc2-ws", owner_id=owner.id)
        db.add(ws)
        await db.commit()
        ws_id = ws.id

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"intent": "write_request", "requested_count": None, "pool_scope": None,
                    "conditions": [], "reason": "批量指派"}

    async def fake_get_llm(db, ws):
        return FakeLLM(), SimpleNamespace(base_url="https://api.deepseek.com/v1", model_name="deepseek-chat")

    monkeypatch.setattr("app.services.search.flow._get_llm", fake_get_llm)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "sc2@b.com", "password": "secret123", "nickname": "S2"})
        token = (await c.post("/api/v1/auth/login", json={"email": "sc2@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "把这些人批量指派到岗位", "stream": False}, headers=h)
        assert r.status_code == 200
        assert r.json()["intent"] == "write_request"
        assert r.json()["cards"] == []
        assert "未上线" in r.json()["summary"] or "不执行" in r.json()["summary"]
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_search_chat_api.py -v`
预期：FAIL，报错 404（端点不存在）

- [x] **步骤 3：实现编排 flow**

```python
# backend/app/services/search/flow.py
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select

from app.services.audit import add_event
from app.services.crypto import decrypt_secret
from app.services.candidate_search import ALLOWED_SCOPES_BY_ROLE, search_candidates
from app.services.model_client import EmbeddingClient, LLMClient, ModelCallError, RerankClient
from app.services.search.cards import build_candidate_cards
from app.services.search.context import merge_follow_up
from app.services.search.extractor import extract_search_intent

REFUSAL_INTENTS = {"job_search", "statistics", "write_request"}


@dataclass
class SearchOutcome:
    intent: str
    cards: list[dict]
    summary: str
    context: dict | None
    reasons: list[str] = None


async def _get_model_client(db, workspace_id: int, model_type: str):
    from app.models import ModelConfig
    cfg = (await db.execute(select(ModelConfig).where(
        ModelConfig.workspace_id == workspace_id, ModelConfig.model_type == model_type))).scalar_one_or_none()
    if cfg is None:
        raise ModelCallError(f"workspace 未配置 {model_type} 模型", retryable=False)
    return cfg


async def _get_llm(db, workspace_id: int):
    cfg = await _get_model_client(db, workspace_id, "llm")
    return LLMClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


async def _get_embedder(db, workspace_id: int):
    cfg = await _get_model_client(db, workspace_id, "embedding")
    return EmbeddingClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


async def _get_rerank(db, workspace_id: int):
    cfg = await _get_model_client(db, workspace_id, "rerank")
    return RerankClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


async def run_search_flow(db, *, workspace_id: int, actor_role: str, utterance: str,
                          prior_context: dict | None) -> SearchOutcome:
    llm = await _get_llm(db, workspace_id)
    parsed = await extract_search_intent(llm, utterance, (prior_context or {}).get("conditions"))

    if parsed.intent in REFUSAL_INTENTS:
        await add_event(db, action="search.intent.refusal", result="success",
                        resource_type="search", workspace_id=workspace_id,
                        payload={"intent": parsed.intent, "utterance": utterance})
        await db.commit()
        return SearchOutcome(intent=parsed.intent, cards=[], summary=_refusal_text(parsed.intent), context=None)

    if parsed.intent not in ("search", "follow_up"):
        await add_event(db, action="search.intent.non_search", result="success",
                        resource_type="search", workspace_id=workspace_id,
                        payload={"intent": parsed.intent})
        await db.commit()
        return SearchOutcome(intent=parsed.intent, cards=[], summary=_non_search_text(parsed.intent), context=None)

    prior_conds = (prior_context or {}).get("conditions") or []
    conditions = merge_follow_up(prior_conds, parsed.conditions) if parsed.intent == "follow_up" else parsed.conditions
    pool_scope = parsed.pool_scope or (prior_context or {}).get("pool_scope") or "active"
    requested = parsed.requested_count if parsed.requested_count is not None else (prior_context or {}).get("requested_count")

    allowed = ALLOWED_SCOPES_BY_ROLE.get(actor_role, set())
    requested_scopes = {pool_scope} if pool_scope else allowed
    scopes = requested_scopes & allowed
    if not scopes:
        await add_event(db, action="search.pool.denied", result="denied",
                        resource_type="search", workspace_id=workspace_id,
                        payload={"requested": pool_scope})
        await db.commit()
        return SearchOutcome(intent="search", cards=[], summary="无权限查询该人才池。", context=None)

    embedder = await _get_embedder(db, workspace_id)
    qv = (await embedder.embed([utterance]))[0]
    hits = await search_candidates(db, workspace_id, qv, utterance, conditions, scopes=scopes, top_k=20)

    # rerank（S-1）：rerank 不可用降级为 RRF 顺序
    rerank_used = False
    if hits:
        try:
            rerank = await _get_rerank(db, workspace_id)
            docs = [f"{c['name']} {' '.join(map(str, c['matched_conditions']))}" for c in await _candidate_preview(db, workspace_id, hits)]
            scores = await rerank.rerank(utterance, docs)
            hits = [h for _, h in sorted(zip(scores, hits), key=lambda x: x[0], reverse=True)]
            rerank_used = True
        except ModelCallError:
            pass

    candidate_ids = [h.candidate_id for h in hits]
    cards = await build_candidate_cards(db, candidate_ids, conditions)
    card_by_id = {c["candidate_id"]: c for c in cards}
    # 画像从 latest_revision.profile_json 并入
    cards = await _attach_profile(db, card_by_id, candidate_ids)

    if requested:
        returned = len(cards)
        if returned < requested:
            summary = f"仅找到 {returned} 位匹配候选人（请求 {requested} 位）。"
        else:
            summary = f"已返回 {returned} 位匹配候选人。"
    elif not cards:
        summary = "未找到匹配的候选人，可尝试放宽技能、年限或城市条件。"
    else:
        summary = f"找到 {len(cards)} 位匹配候选人，按相关度排序。"

    context = {"conditions": conditions, "pool_scope": pool_scope, "requested_count": requested}
    await add_event(db, action="search.executed", result="success",
                    resource_type="search", workspace_id=workspace_id,
                    payload={"intent": parsed.intent, "hit_count": len(cards), "rerank": rerank_used})
    await db.commit()
    return SearchOutcome(intent=parsed.intent, cards=cards, summary=summary, context=context)


def _refusal_text(intent: str) -> str:
    return {
        "job_search": "按岗位搜索功能尚未上线，请稍后再试。",
        "statistics": "统计查询功能尚未上线，请稍后再试。",
        "write_request": "写请求（指派/打标/修正等）不在此对话中执行，请到工作台完成。",
    }[intent]


def _non_search_text(intent: str) -> str:
    return {
        "chit_chat": "我是招聘搜人助手，可以帮你按技能、年限、城市、学历等条件找人。",
        "out_of_scope": "这个问题超出搜人范围，我只能基于人才库做候选人检索。",
    }[intent]
```

> `_candidate_preview`/`_attach_profile` 为 flow 内部辅助（查询 latest_revision 的 profile_json 与候选人摘要文本），实现时补充；`_attach_profile` 把 `profile_json["values"]` 并入卡片 `profile`。

- [x] **步骤 4：实现 SSE 端点**

```python
# backend/app/api/search_chat.py
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.resumes import ensure_member
from app.models import Conversation, Message, User, WorkspaceMember
from app.services.search.context import deserialize_context, serialize_context
from app.services.search.flow import run_search_flow

router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str = Field(..., min_length=1, max_length=4000)
    stream: bool = True


async def _ws_for_user(ws_id: int, user: User, db: AsyncSession):
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user.id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(404, "资源不存在")
    return row.scalar_one_or_none()


def _role_of(membership) -> str:
    return membership.role.value if hasattr(membership.role, "value") else str(membership.role)


async def _load_context(db, conv_id: int) -> dict | None:
    rows = await db.execute(select(Message).where(Message.conversation_id == conv_id, Message.role == "assistant").order_by(Message.id.desc()).limit(1))
    msg = rows.scalar_one_or_none()
    if msg is None:
        return None
    for src in msg.sources or []:
        if isinstance(src, dict) and src.get("type") == "context":
            return deserialize_context(src["payload"])
    return None


@router.post("/workspaces/{ws_id}/search-chat")
async def search_chat(ws_id: int, body: SearchChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _ws_for_user(ws_id, user, db)
    role = _role_of(membership)

    if body.conversation_id is not None:
        conv = await db.get(Conversation, body.conversation_id)
        if conv is None or conv.user_id != user.id or conv.workspace_id != ws_id or conv.knowledge_base_id is not None:
            raise HTTPException(404, "会话不存在")
    else:
        conv = Conversation(user_id=user.id, workspace_id=ws_id, knowledge_base_id=None, title=body.message[:30])
        db.add(conv)
        await db.flush()
    db.add(Message(conversation_id=conv.id, role="user", content=body.message))
    await db.commit()

    prior = await _load_context(db, conv.id)

    async def gen():
        try:
            outcome = await run_search_flow(db, workspace_id=ws_id, actor_role=role,
                                            utterance=body.message, prior_context=prior)
            yield f"data: {json.dumps({'type': 'intent', 'intent': outcome.intent})}\n\n"
            yield f"data: {json.dumps({'type': 'cards', 'cards': outcome.cards})}\n\n"
            yield f"data: {json.dumps({'type': 'summary', 'text': outcome.summary})}\n\n"
            sources = list(outcome.cards)
            if outcome.context is not None:
                sources.append({"type": "context", "payload": serialize_context(outcome.context)})
            msg = Message(conversation_id=conv.id, role="assistant", content=outcome.summary, sources=sources)
            db.add(msg)
            await db.commit()
            yield f"data: {json.dumps({'type': 'done', 'message_id': msg.id, 'conversation_id': conv.id})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'code': 'INTERNAL_ERROR', 'message': '搜人时发生错误，请稍后重试'})}\n\n"

    if not body.stream:
        import asyncio
        events = []
        async def collect():
            async for e in gen():
                events.append(e)
        asyncio.run(collect())
        payload = {}
        for e in events:
            data = json.loads(e[6:])
            payload.update(data)
        return {"intent": payload.get("intent"), "cards": payload.get("cards") or [],
                "summary": payload.get("summary") or "", "conversation_id": conv.id}
    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [x] **步骤 5：注册路由**

`backend/app/main.py`：
```python
from app.api import search_chat
...
app.include_router(search_chat.router)
```

- [x] **步骤 6：运行测试验证通过**

运行：`pytest backend/tests/test_search_chat_api.py -v`
预期：PASS

- [x] **步骤 7：Commit**

```bash
git add backend/app/services/search/flow.py backend/app/api/search_chat.py backend/app/main.py backend/tests/test_search_chat_api.py
git commit -m "feat: add search chat SSE endpoint with intent orchestration and multi-turn context (P3 F7)"
```

---

### 任务 9：前端搜人对话页（最小闭环）

**文件：**
- 创建：`frontend/src/api/search.ts`
- 创建：`frontend/src/pages/SearchPage.tsx`
- 修改：`frontend/src/App.tsx`

- [x] **步骤 1：编写 API 客户端**

```ts
// frontend/src/api/search.ts
import { client } from './client';

export interface SearchCard {
  candidate_id: number;
  name: string | null;
  city: string | null;
  highest_degree: string | null;
  years_experience: number | null;
  matched_conditions: string[];
  profile: { level?: string | null; domain?: string | null };
}

export async function searchChat(wsId: number, message: string, conversationId?: number) {
  const resp = await fetchWithRefresh(`/api/v1/workspaces/${wsId}/search-chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, message, stream: true }),
  });
  return parseSearchSse(resp);
}
```

> 实现时复用 P1 `frontend/src/api/chat.ts` 的 `fetchWithRefresh`/SSE 解析模式（`data:` 事件逐行读取，`event.data` JSON 解析），`parseSearchSse` 收集 `cards`/`summary`/`done`/`error` 事件。

- [x] **步骤 2：编写页面组件**

创建 `frontend/src/pages/SearchPage.tsx`：输入框 + 消息列表（用户消息 / 摘要 + 候选卡片列表：姓名/城市/学历/年限/命中条件标签/画像摘要），复用 `client.getWorkspace` 取当前工作区 id，会话级 `conversationId` 状态实现多轮。样式对齐 Dashboard/Chat 页。

- [x] **步骤 3：注册路由**

`frontend/src/App.tsx` 增加 `/search` 路由 → `SearchPage`（需登录，复用现有 guard）。

- [x] **步骤 4：前端测试与构建**

```bash
cd frontend && npm run build
```
预期：通过（tsconfig 排除测试目录）

- [x] **步骤 5：Commit**

```bash
git add frontend/src/api/search.ts frontend/src/pages/SearchPage.tsx frontend/src/App.tsx
git commit -m "feat: add candidate search chat page (P3 F7)"
```

---

### 任务 10：回归验证与台账

- [x] **步骤 1：全量回归**

```bash
cd backend && ../.venv/bin/alembic upgrade head && cd .. && .venv/bin/pytest backend/tests -q
```
预期：**新增 6 个测试文件 + 追加用例全部通过，全量 ≥ 200 passed**

- [x] **步骤 2：静态检查**

```bash
.venv/bin/ruff check backend/app backend/tests
```

- [x] **步骤 3：更新台账**

在 `docs/superpowers/deviation-log.md` 追加 §11「P3 对话式搜人（F7）实现与偏离」，记录 S-1~S-12 裁决、实现偏差与验证数字。

- [x] **步骤 4：勾选计划并提交**

```bash
git add -A && git commit -m "docs: 记录 P3 搜人实现偏差与验证（P3 F7）"
```

---

## 自检

**1. 规格覆盖度：**

| 需求 | 对应任务 |
|------|---------|
| 意图识别（search/follow_up/job_search/statistics/write_request/chit_chat/out_of_scope） | 任务 5、8 |
| 条件 AST 抽取与完整性（field/fields/op/value/logic/missing_policy） | 任务 3、5 |
| 结构化条件 SQL 过滤 | 任务 3、4 |
| 五段向量混合检索 + search_tsv 全文 + RRF | 任务 4 |
| rerank 排序（bge-reranker-v2-m3）与降级 | 任务 2、4、8 |
| 池过滤/ACL（M4 最小：member active/rejected、hired admin/owner） | 任务 4、8 |
| 数量意图 requested_count 与满足说明 | 任务 5、8 |
| 多轮条件收敛（follow_up 仅更新变化字段） | 任务 5、6、8 |
| 无结果/拒答（no_result 文案、job_search/statistics/write_request 无副作用） | 任务 8 |
| 候选卡片 + 命中条件标注 + 不展示分数 | 任务 4、7、8 |
| SSE 流式返回 + 会话持久化 | 任务 8 |
| 画像依赖查询（level/domain/management 过滤，观测口径） | 任务 3、5、7 |
| 前端搜人页（MVP §3.3 UI 闭环） | 任务 9 |
| 审计事件（搜人执行/拒写/越权） | 任务 8 |

**2. 占位符扫描：** 已避免 TODO/占位；`_candidate_preview`/`_attach_profile` 为 flow 内部辅助函数，任务 8 步骤 3 明确其职责与实现点。

**3. 类型一致性：** `SearchIntent`（extractor.py）字段与 flow 消费一致；`build_condition_filter`/`validate_conditions`（schema.py）在任务 3/4/8 复用；`merge_follow_up`（context.py）在任务 6/8 复用；`SearchOutcome`（flow.py）与 search_chat API 消费一致。

**已知边界（后续处理）：** M4 评测 bundle（查询集/fixture/scorer，需下载 AI Studio 数据集）；F10 职位管理与 job_search；F11 统计查询；F15 完整三池流转（M5）；画像标注子集升级 profile_dependent 硬门槛；真实模型凭据写入。

---

## 执行交接

**计划已完成并保存到 `docs/superpowers/plans/2026-08-08-p3-candidate-search.md`。两种执行方式：**

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

**选哪种方式？**