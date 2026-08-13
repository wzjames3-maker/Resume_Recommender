# P2 简历解析流水线（F6）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现 F6 简历解析与入库流水线——双通道文本抽取 → Markdown IR → PII 前置脱敏 → 两阶段 LLM 结构化 → AI 人才画像 → 查重 → 入库（PII 加密 + 五段向量 + 全文索引），并以 run_id 幂等、失败分类重试、全链路审计产物落库。跑通 M3 核心链路，为 P3 搜人（F7）提供候选人数据。

**架构：** 在 P1 平台底座（F1–F5，已合并至 main）上新增独立简历领域。抽取/IR/PII/结构化/画像为纯 Python 服务层；解析全流程由 Celery 任务 `parse_resume` 编排，run 状态机 + Redis lease + DB 唯一约束三重保证幂等；真实 LLM（deepseek-chat）与 embedding（bge-m3）经 P1 出站网关调用，PII 脱敏在任何出站调用之前执行。候选人/解析 run/审计 使用新表，与 F3 知识库（documents/chunks）领域完全隔离。

**技术栈：** FastAPI、SQLAlchemy 2.0（async）、Alembic、Celery、PostgreSQL 16 + pgvector、Redis、python-docx、pypdf、LibreOffice headless（兜底通道）、httpx、pytest、pydantic v2。

**参考：** `docs/PRD.md` §7.2 F6、`docs/superpowers/specs/2026-08-07-resume-schema-and-import.md`、`docs/superpowers/specs/2026-08-07-resume-quality-evaluation.md`、`docs/superpowers/specs/2026-08-07-mvp-scope-and-acceptance.md` §3、`docs/superpowers/deviation-log.md` §4。

---

## 设计决策与歧义裁决（实现前必读）

以下为 PRD / 四份 spec / deviation-log 之间的歧义或实现取舍，本计划显式裁决。实现者不得静默更改。

| # | 歧义 / 取舍 | 依据 | 本计划裁决 |
|---|------------|------|-----------|
| A-1 | 两阶段 LLM 结构化可合并为单次调用 | PRD F6 注「两阶段可合并为单次调用，由技术设计按 token 成本与准确率实测确定」 | **P2 实现单次调用**：阶段二直接输出完整 Schema JSON（含 evidence）。`structured.py` 保留阶段一接口（`detect_structure`）与 Prompt 模板占位，但流水线默认走单次调用；若评测分类别 F1 不达标，再启用两阶段（改一行配置）。理由：token 成本低、实现简单、M3 门槛先由单次调用验证 |
| A-2 | 解析自动重试次数 | PRD F6「最多自动重试 2 次、指数退避」；评测 spec §6「结构化输出校验失败重试一次」；评测 spec §2.5 runtime「评测按 §6 单次重试；生产按 PRD 最多自动 2 次」 | 非冲突，是生产/评测两态。配置 `RESUME_MAX_AUTO_RETRIES`（默认生产 2；评测 manifest 运行时设 1）。重试仅限 `retryable` 失败类（超时/限流/网络）；`not_retryable`（格式/安全/Schema）不自动重试 |
| A-3 | rerank（bge-reranker-v2-m3）何时接入 | deviation-log §4「真实 embedding/LLM/rerank 接入 → P2/P3」；PRD F6 入库不涉及 rerank（rerank 属 F7 搜人） | **P2 只接 embedding + LLM**（F6 需要）；rerank 留 P3（F7 搜人）。本计划不实现 rerank 客户端 |
| A-4 | .doc 旧格式支持依赖 LibreOffice | PRD F6 兜底通道「LibreOffice headless」；worker 镜像需内置 | P2 在 `backend/Dockerfile` 安装 LibreOffice headless；抽取器含 `LibreOfficeConverter` 兜底。若运行环境无法安装 soffice，.doc/主力抽取失败降级为 `not_retryable` 拒绝并返回明确错误（测试用 mock 的 .doc 路径，不依赖真实 soffice） |
| A-5 | 查重命中后的合并操作 | PRD F12「命中提示合并」；F12 属 P0-核心（P3 计划） | P2 实现**查重检测**（姓名 + phone/email 哈希精确匹配，软删除记录仍参与）与 `pending_review` 状态；**合并动作留 P3**（F12）。命中时候选人不以 `active` 入库，标记 `pending_review` 并返回命中列表 |
| A-6 | 人工修正 override/clear | Schema spec §2「字段优先级与 revision」 | P2 建 `candidate_overrides` 表 + 读取合并视图逻辑（最新 revision 值 + override/clear 覆盖）；**修正写入 API 与 UI 留 P3**（F8 候选人管理） |
| A-7 | 软删除生命周期 | PRD F8「active→deleted→purged」 | P2 建 `status`/`deleted_until` 字段 + 软删除从检索/查重口径处理；**删除/恢复 API 留 P3**（F8） |
| A-8 | embedding 维度 | P1 `EMBEDDING_DIM=1024`（bge-m3 默认为 1024） | 保持 1024；真实 embedding 客户端校验返回维度，不一致抛 `not_retryable` 错误 |
| A-9 | 全文索引中文分词 | PRD F6 入库要全文索引；P1 全文检索为 ILIKE 简化 | P2 建 `candidate_search_text` 列 + `tsvector` GIN 索引（`simple` 配置，空格分词）；中文分词（pg_jieba 等）与 ILIKE 兜底留 P3 搜人 |
| A-10 | CSV 导入不纳入字段 F1 | Schema spec §3「CSV 经历数组为 null，不纳入结构化字段 F1 评测」 | 无冲突，仅记录：CSV 导入候选人经历数组为 `null`，保留 `import_summary` 供检索文本 |
| A-11 | 画像第三层（Candidate×Job 动态匹配） | PRD F6「第三层不预存，惰性计算」 | P2 只实现第一层（固定八维枚举）+ 第二层（开放洞察）并落库；**第三层动态匹配留 P3**（F7 搜人/指派触发时计算） |
| A-12 | 解析审计链四级产物 hash | PRD F6「原文件→IR→candidate.json→画像 四级产物 + hash」 | P2 实现 IR/candidate/profile 三级产物 hash（`sha256`）落 parse_runs 表，原文件 hash 落 resume_files；`evidence` 用 `ir_revision_id + block_id + start_offset + end_offset + quote_hash` 引用同一 run 的 IR |
| A-13 | evidence 的 quote_hash 由谁计算 | Schema spec §1「引用不存在或 hash 不匹配时不得发布结果」；LLM 无法可靠计算 sha256 | Prompt 要求 LLM 输出 `block_id + start_offset + end_offset + quote`（原文引用串）；**系统侧**校验 quote 必须逐字出现在对应 block 文本中（防编造），定位以实际出现位置为准（LLM 提供的 offset 偏差时静默修正），`quote_hash = sha256(quote)[:16]` 由系统计算后落库（A-12 存储格式不变）。evidence 引用的是**脱敏后 IR**（脱敏为确定性映射，可由落库 IR 重放推导） |
| A-14 | run 终态映射 | PRD F6「不可重试（格式/安全/Schema）与可重试；最多自动重试 2 次；连续失败进入 dead-letter」 | `not_retryable` → 直接 `failed`（failure_class=not_retryable，人工可重试）；`retryable` 自动重试耗尽 → `dead_letter`（连续失败，等待人工处理）。人工 retry 一律生成新 run_id |
| A-15 | PII taxonomy 中姓名/地址的脱敏范围 | PRD F6 ④ taxonomy 列「手机号/身份证/邮箱、姓名、地址」；但 F8/F12 要求姓名可展示、可查重、可搜索 | 脱敏目标为 **phone/email/id_card + 提示词式姓名**（「姓名: X」模式）；姓名明文落 `candidates.name`（查重/展示/搜索必需，本地存储不出站）；**地址**不在统一 Schema 字段内（city/hometown 为可搜索/展示字段），不参与出站脱敏。段落/摘要向量文本不含 phone/email/姓名 |
| A-16 | F5 chat 检索链路的 embedder | deviation-log §4「真实 embedding 接入 → P2」；P1 chat 用全局占位 embedder，KB chunks 为占位零向量 | P2 只在**简历流水线**接入真实 bge-m3（workspace 级 model_config）；`app/rag/embedder.py` 全局占位行为**不改**（改了会破坏 F5 chat 与 P1 回归测试），KB 真实向量化随 F3 重解析留 P3。实现时记入 deviation-log |
| A-17 | CSV/JSON 导入的 run 粒度 | PRD F6「csv/json 跳过 LLM 直接映射」+「按 row_hash 仅重试失败行」；run 幂等为 1 run : 1 候选人 | 上传的 CSV 在 API 层展开为行、JSON envelope 展开为记录，**每行/记录写一个 JSON 记录文件并生成独立 run**（format=json），row_hash 落 `parse_runs.file_hash`；流水线 json 分支跳过抽取/IR 阈值/LLM/画像，直接校验→派生字段→查重→向量化→入库。CSV 原件不单独留存（行级 JSON 产物为审计件），记入 deviation-log |
| A-18 | Redis lease 的定位 | 用户约束「Redis lease + DB 唯一约束 + 状态检查三重保障」 | Redis lease 为**尽力而为**的执行互斥（SET NX EX，Redis 不可用时降级放行并告警）；真正的幂等兜底是 DB 侧：`candidate_revisions.revision_id` 唯一（revision_id = run_id 派生）+ ingest 前置状态检查。lease 不替代 DB 保障 |
| A-19 | 上传格式含 pdf | PRD F6 ① 列 doc/docx/txt/csv/json（下限而非上限）；评测 format 仅 doc/docx/txt | **保留 pdf 为受支持格式**：抽取器/安全校验/内容类型映射已全线支持，PDF 简历为实际高频格式，移除会产生死代码；不影响 M3 评测口径。实现时记入 deviation-log |

---

## 文件结构

```
backend/
  pyproject.toml                            (修改：+ python-docx, pypdf)
  Dockerfile                                (修改：+ LibreOffice headless)
  alembic/versions/8f4e2d1a9c0b_add_resume_tables.py (新：增量迁移)
  app/
    models/
      parse_run.py                          (新：解析 run 表)
      candidate.py                          (新：candidates / candidate_revisions / candidate_overrides / resume_files / resume_irs / candidate_embeddings / pii_mappings)
      audit_event.py                        (新：不可变审计事件)
      __init__.py                           (修改：导出新模型)
    api/
      resumes.py                            (新：F6 端点：批量上传/导入/进度/IR/重试/详情)
    services/
      model_client.py                       (新：LLM/embedding 客户端，读 ModelConfig + 出站网关)
      audit.py                              (新：审计事件写入)
      crypto.py                             (复用，不修改；PII 加密辅助放 pii.py/ingest.py)
      outbound_gateway.py                   (修改：新增 http_post_json 辅助)
      resume/
        __init__.py                         (空)
        safety.py                           (新：文件安全校验：ZIP 炸弹/XML 深度/宏/加密/资源上限)
        extractor.py                        (新：docx 双通道 + pdf 文本层 + txt + LibreOffice 兜底)
        ir.py                               (新：Markdown IR 归一化 + 有效性校验)
        pii.py                              (新：PII 识别与脱敏 + token 还原，fail-closed)
        structured.py                       (新：两阶段 LLM 结构化 + Schema/evidence 校验 + 失败分类)
        profile.py                          (新：AI 人才画像 八维 + 开放洞察)
        dedup.py                            (新：查重归一化与精确匹配)
        derive.py                           (新：years_experience 派生 + conflict 检测)
        segments.py                         (新：五段检索文本构建)
        ingest.py                           (新：入库：PII 加密落库 + 五段向量 + 全文索引)
        importers.py                        (新：CSV/JSON 导入解析与记录文件落盘)
        pipeline.py                         (新：阶段编排 + run 状态机 + json 导入分支)
    tasks/
      parse_resume.py                       (新：Celery 任务 + Redis lease + run 幂等 + 显式重试)
      celery_app.py                         (修改：include 增加 parse_resume)
    rag/
      embedder.py                           (不改：A-16 裁决保留占位，简历流水线直连 EmbeddingClient)
  tests/
    conftest.py                             (修改：TRUNCATE 表清单扩展新表；注入 RESUME_MAX_AUTO_RETRIES)
    test_resume_models.py
    test_safety.py
    test_pii.py
    test_extractor.py
    test_ir.py
    test_structured.py
    test_profile.py
    test_model_client.py
    test_parse_resume.py
    test_resumes_api.py
    test_ingest.py
    test_derive.py
```

**领域边界**：P2 不修改 P1 的 `Document`/`Chunk`/`KnowledgeBase` 模型与 `parse_document` 任务（F3 知识库领域独立）。`parse_document.py` 的 docx/pdf 占位失败行为保持不变；P2 只新增简历领域的抽取/IR/结构化。

---

### 任务 1：简历领域数据模型与迁移

**文件：**
- 创建：`backend/app/models/parse_run.py`
- 创建：`backend/app/models/candidate.py`
- 创建：`backend/app/models/audit_event.py`
- 修改：`backend/app/models/__init__.py`
- 创建：`backend/alembic/versions/8f4e2d1a9c0b_add_resume_tables.py`
- 测试：`backend/tests/test_resume_models.py`

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_resume_models.py
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models.base import Base
from app.models import (
    ParseRun, ParseRunStatus, Candidate, CandidateStatus,
    CandidateRevision, CandidateOverride, OverrideAction,
    ResumeFile, ResumeIR, CandidateEmbedding, EmbeddingSegment,
    PIIMapping, PIIType, AuditEvent,
)

@pytest.mark.asyncio
async def test_parse_run_roundtrip():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession)
    async with Session() as s:
        run = ParseRun(run_id="run-1", workspace_id=1, upload_id="up-1",
                       source_channel="referral", format="docx",
                       file_hash="abc", file_path="/tmp/x.docx", file_size=100,
                       parser_version="0.1.0", status=ParseRunStatus.pending)
        s.add(run)
        await s.commit()
        got = (await s.execute(select(ParseRun).where(ParseRun.run_id == "run-1"))).scalar_one()
        assert got.status == ParseRunStatus.pending
    await engine.dispose()

@pytest.mark.asyncio
async def test_candidate_and_revision_roundtrip():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession)
    async with Session() as s:
        c = Candidate(workspace_id=1, status=CandidateStatus.active,
                      name="张三", phone_hash="h1", email_hash="h2")
        s.add(c)
        await s.flush()
        s.add(CandidateRevision(candidate_id=c.id, run_id="run-1", revision_id="rev-1",
                                candidate_json={"name": "张三"}, evidence={}))
        s.add(CandidateOverride(candidate_id=c.id, revision_id="rev-1",
                                field_path="name", action=OverrideAction.clear, actor_id=1))
        s.add(ResumeFile(run_id="run-1", candidate_id=c.id, file_hash="abc",
                         storage_key="/tmp/x.docx", format="docx", file_size=100,
                         content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        s.add(ResumeIR(run_id="run-1", content="# 张三", valid_chars=3))
        # SQLite variant 下 embedding 列为 Text，绑定 str；PG 下 Vector 列由流水线绑定 list
        s.add(CandidateEmbedding(candidate_id=c.id, revision_id="rev-1",
                                 segment=EmbeddingSegment.work, text="支付系统", embedding="[0.1,0.2]"))
        s.add(PIIMapping(run_id="run-1", pii_type=PIIType.phone, content_hash="ch", token_enc="tok"))
        a = AuditEvent(event_id="evt-1", action="parse.run.start", result="success",
                       resource_type="parse_run")
        s.add(a)
        await s.commit()
        assert (await s.execute(select(Candidate).where(Candidate.name == "张三"))).scalar_one().status == CandidateStatus.active
        assert (await s.execute(select(AuditEvent).where(AuditEvent.event_id == "evt-1"))).scalar_one().action == "parse.run.start"
    await engine.dispose()
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_resume_models.py -v`
预期：FAIL，报错 "ModuleNotFoundError: No module named 'app.models.parse_run'"

 - [x] **步骤 3：创建 parse_run 模型**

```python
# backend/app/models/parse_run.py
import enum

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK, TimestampMixin


class ParseRunStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"
    dead_letter = "dead_letter"


class FailureClass(str, enum.Enum):
    not_retryable = "not_retryable"
    retryable = "retryable"


class ParseRun(Base, TimestampMixin):
    __tablename__ = "parse_runs"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    workspace_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    upload_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_channel: Mapped[str] = mapped_column(String(32), nullable=False)
    template_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(64), nullable=True)  # spec v0.5 冻结：内推人（邮箱或姓名≤64）
    format: Mapped[str] = mapped_column(String(16), nullable=False)  # doc/docx/txt/csv/json
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[ParseRunStatus] = mapped_column(Enum(ParseRunStatus, name="parse_run_status", values_callable=lambda e: [m.value for m in e]), nullable=False, default=ParseRunStatus.pending, index=True)
    failure_class: Mapped[FailureClass | None] = mapped_column(Enum(FailureClass, name="failure_class", values_callable=lambda e: [m.value for m in e]), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ir_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
```

 - [x] **步骤 4：创建 candidate 相关模型**

```python
# backend/app/models/candidate.py
import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON, BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK, TimestampMixin
from app.models.chunk import EMBEDDING_DIM

# PG 用 tsvector + GIN 全文索引；SQLite 测试用 Text 占位
TSVECTOR = postgresql.TSVECTOR().with_variant(Text, "sqlite")


class CandidateStatus(str, enum.Enum):
    active = "active"
    deleted = "deleted"
    purged = "purged"
    pending_review = "pending_review"


class OverrideAction(str, enum.Enum):
    override = "override"
    clear = "clear"


class EmbeddingSegment(str, enum.Enum):
    summary = "summary"
    education = "education"
    work = "work"
    project = "project"
    skills = "skills"


class PIIType(str, enum.Enum):
    phone = "phone"
    email = "email"
    id_card = "id_card"
    name = "name"
    address = "address"


class Candidate(Base, TimestampMixin):
    __tablename__ = "candidates"
    __table_args__ = (
        Index("ix_candidates_workspace_status", "workspace_id", "status"),
        Index("ix_candidates_dedup", "workspace_id", "name", "phone_hash", "email_hash", postgresql_where=text("status IN ('active','deleted','pending_review')")),
        Index("ix_candidates_search_tsv", "search_tsv", postgresql_using="gin"),
    )
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[CandidateStatus] = mapped_column(Enum(CandidateStatus, name="candidate_status", values_callable=lambda e: [m.value for m in e]), nullable=False, default=CandidateStatus.active, index=True)
    deleted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    structured_data: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict)
    latest_revision_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    search_tsv = mapped_column("search_tsv", TSVECTOR, nullable=False, server_default="")


class CandidateRevision(Base):
    __tablename__ = "candidate_revisions"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    candidate_json: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    profile_json: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict)
    conflicts: Mapped[list] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CandidateOverride(Base):
    __tablename__ = "candidate_overrides"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    before_value = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    after_value = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    action: Mapped[OverrideAction] = mapped_column(Enum(OverrideAction, name="override_action", values_callable=lambda e: [m.value for m in e]), nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ResumeFile(Base):
    __tablename__ = "resume_files"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ResumeIR(Base):
    __tablename__ = "resume_irs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    valid_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CandidateEmbedding(Base):
    __tablename__ = "candidate_embeddings"
    __table_args__ = (Index("ix_candidate_embeddings_hnsw", "embedding", postgresql_using="hnsw", postgresql_with={"m": 16, "ef_construction": 64}, postgresql_ops={"embedding": "vector_cosine_ops"}),)
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    segment: Mapped[EmbeddingSegment] = mapped_column(Enum(EmbeddingSegment, name="embedding_segment", values_callable=lambda e: [m.value for m in e]), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIM).with_variant(Text, "sqlite"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PIIMapping(Base):
    __tablename__ = "pii_mappings"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pii_type: Mapped[PIIType] = mapped_column(Enum(PIIType, name="pii_type", values_callable=lambda e: [m.value for m in e]), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    ir_locator = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

 - [x] **步骤 5：创建审计事件模型**

```python
# backend/app/models/audit_event.py
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = ({"comment": "不可变审计事件：只 append，无 update/delete 路径"},)
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)  # success / failure / denied
    before_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
```

 - [x] **步骤 6：更新 __init__ 并生成迁移**

```python
# backend/app/models/__init__.py 追加
from app.models.parse_run import FailureClass, ParseRun, ParseRunStatus
from app.models.candidate import (
    Candidate, CandidateEmbedding, CandidateOverride, CandidateRevision,
    CandidateStatus, EmbeddingSegment, OverrideAction, PIIMapping, PIIType,
    ResumeFile, ResumeIR,
)
from app.models.audit_event import AuditEvent

__all__ += [
    "ParseRun", "ParseRunStatus", "FailureClass",
    "Candidate", "CandidateStatus", "CandidateRevision", "CandidateOverride",
    "OverrideAction", "ResumeFile", "ResumeIR", "CandidateEmbedding",
    "EmbeddingSegment", "PIIMapping", "PIIType", "AuditEvent",
]
```

```bash
cd backend
alembic revision --autogenerate -m "add resume pipeline tables"
# 检查生成的迁移：确认新增 9 张表、索引（dedup 部分索引、search_tsv GIN、embeddings HNSW）
# 注意：Candidate.search_tsv 在 SQLite variant 用 Text，PG 用 tsvector —— 若 autogenerate 生成
# 的是 Text，需手动改为：
#   sa.Column('search_tsv', postgresql.TSVECTOR(), server_default='', nullable=False),
# downgrade 同步移除
alembic upgrade head
```

自生成迁移之外，手工补充全文索引维护 trigger（否则 `search_tsv` 默认空值，GIN 索引不会检索到 `search_text`）：

```python
# backend/alembic/versions/8f4e2d1a9c0b_add_resume_tables.py
from alembic import op


def upgrade() -> None:
    # ... autogenerate 生成的 9 张表与索引 ...
    op.execute("""
    CREATE FUNCTION candidates_search_tsvector_sync() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      NEW.search_tsv := to_tsvector('simple', coalesce(NEW.search_text, ''));
      RETURN NEW;
    END $$;
    """)
    op.execute("""
    CREATE TRIGGER candidates_search_tsvector_sync
    BEFORE INSERT OR UPDATE OF search_text ON candidates
    FOR EACH ROW EXECUTE FUNCTION candidates_search_tsvector_sync();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS candidates_search_tsvector_sync ON candidates")
    op.execute("DROP FUNCTION IF EXISTS candidates_search_tsvector_sync()")
    # ... autogenerate 生成的反向删除 ...
```

迁移验收：在 PG 中插入 `search_text='Java Spring'` 的候选人，确认
`search_tsv @@ plainto_tsquery('simple', 'Spring')` 为真；SQLite 模型测试只验证列可写，不执行 PostgreSQL 全文函数。

迁移应用后**立即**扩展 conftest 清理表清单（新表已存在，TRUNCATE 不会失败；任务 9/11 的 PG 测试依赖此清理）：

```python
# backend/tests/conftest.py 修改
_CLEANUP_TABLES = "candidate_embeddings, candidate_overrides, candidate_revisions, resume_irs, resume_files, pii_mappings, candidates, parse_runs, audit_events, workspace_members, workspaces, users"
```

 - [x] **步骤 7：运行测试验证通过**

运行：`pytest backend/tests/test_resume_models.py -v`
预期：PASS

 - [x] **步骤 8：Commit**

```bash
git add backend/app/models backend/alembic/versions backend/tests/test_resume_models.py backend/tests/conftest.py
git commit -m "feat: add resume pipeline data models and migration (P2 F6)"
```

---

### 任务 2：文件解析安全校验

**文件：**
- 创建：`backend/app/services/resume/__init__.py`
- 创建：`backend/app/services/resume/safety.py`
- 测试：`backend/tests/test_safety.py`

**验收（MVP §3.3）：** 加密/宏/嵌入对象/压缩炸弹默认拒收；解压后 ≤100MB、XML 深度 ≤100、对象 ≤20、CPU ≤60s、内存 ≤1GB、临时磁盘 ≤500MB；worker 重启后临时目录清理。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_safety.py
import io
import zipfile

import pytest

from app.services.resume.safety import (
    MAX_XML_DEPTH, MAX_EMBEDDED_OBJECTS, MAX_UNCOMPRESSED_SIZE,
    validate_docx_zip, validate_pdf, resource_limits,
)


def _make_docx(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_macro_docx_rejected():
    data = _make_docx({
        "word/document.xml": "<w:document/>",
        "word/vbaProject.bin": b"MACRO",
    })
    with pytest.raises(ValueError, match="宏"):
        validate_docx_zip(io.BytesIO(data))


def test_encrypted_docx_rejected():
    data = _make_docx({
        "word/document.xml": "<w:document/>",
        "word/encryption.xml": "<enc/>",
    })
    with pytest.raises(ValueError, match="加密"):
        validate_docx_zip(io.BytesIO(data))


def test_zip_bomb_uncompressed_limit():
    # 压缩比极高：4MB 同字符压缩到很小，但解压后超过限制
    bomb = b"a" * (MAX_UNCOMPRESSED_SIZE + 1024)
    data = _make_docx({"word/document.xml": bomb})
    with pytest.raises(ValueError, match="解压后大小"):
        validate_docx_zip(io.BytesIO(data))


def test_deep_xml_rejected():
    depth = MAX_XML_DEPTH + 5
    nested = "<a>" * depth + "x" + "</a>" * depth
    data = _make_docx({"word/document.xml": nested})
    with pytest.raises(ValueError, match="XML 深度"):
        validate_docx_zip(io.BytesIO(data))


def test_too_many_embedded_objects_rejected():
    files = {"word/document.xml": "<w:document/>"}
    for i in range(MAX_EMBEDDED_OBJECTS + 1):
        files[f"word/embeddings/oleObject{i}.bin"] = b"obj"
        files[f"word/embeddings/package{i}.bin"] = b"bin"
    data = _make_docx(files)
    with pytest.raises(ValueError, match="嵌入对象"):
        validate_docx_zip(io.BytesIO(data))


def test_encrypted_pdf_rejected(tmp_path):
    import pypdf
    p = tmp_path / "enc.pdf"
    writer = pypdf.PdfWriter()
    writer.append_blank_page(width=200, height=200)
    writer.encrypt("secret")
    with open(p, "wb") as f:
        writer.write(f)
    with pytest.raises(ValueError, match="加密"):
        validate_pdf(str(p))


def test_clean_mean_docx_accepted():
    data = _make_docx({"word/document.xml": "<w:document><w:body/></w:document>"})
    validate_docx_zip(io.BytesIO(data))  # 不抛异常


def test_resource_limits_restores_previous_limits():
    import resource as res
    before_cpu = res.getrlimit(res.RLIMIT_CPU)
    before_as = res.getrlimit(res.RLIMIT_AS)
    with resource_limits(cpu_seconds=1, mem_bytes=64 * 1024 * 1024):
        assert res.getrlimit(res.RLIMIT_CPU)[0] == 1
    # 退出后必须还原，否则会杀死后续测试进程（RLIMIT_CPU 为累计值）
    assert res.getrlimit(res.RLIMIT_CPU) == before_cpu
    assert res.getrlimit(res.RLIMIT_AS) == before_as


def test_check_file_signature():
    from app.services.resume.safety import check_file_signature
    check_file_signature(b"PK\x03\x04data", "docx")          # zip 魔数
    check_file_signature(b"%PDF-1.4", "pdf")
    check_file_signature(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "doc")  # OLE2
    check_file_signature(b"plain text", "txt")
    with pytest.raises(ValueError, match="签名"):
        check_file_signature(b"%PDF-1.4", "docx")
    with pytest.raises(ValueError, match="签名"):
        check_file_signature(b"\x00\x01\x02", "txt")          # 文本含 NUL
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_safety.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

 - [x] **步骤 3：实现安全校验**

```python
# backend/app/services/resume/safety.py
import io
import zipfile
from contextlib import contextmanager

MAX_UNCOMPRESSED_SIZE = 100 * 1024 * 1024  # 解压后 ≤100MB
MAX_XML_DEPTH = 100
MAX_EMBEDDED_OBJECTS = 20
MAX_DISK_BYTES = 500 * 1024 * 1024  # 临时磁盘 ≤500MB
MAX_CONVERT_OUTPUT = 50 * 1024 * 1024  # 转换输出 ≤50MB


def _iter_zip_members(zf: zipfile.ZipFile):
    total = 0
    for info in zf.infolist():
        total += info.file_size
        if total > MAX_UNCOMPRESSED_SIZE:
            raise ValueError(f"解压后大小超过 {MAX_UNCOMPRESSED_SIZE} 限制")
        yield info


def validate_docx_zip(data: bytes | io.BytesIO) -> None:
    try:
        zf = zipfile.ZipFile(data)
    except zipfile.BadZipFile as exc:
        raise ValueError("不是合法的 docx (zip) 文件") from exc

    names = set(zf.namelist())
    if "word/vbaProject.bin" in names or any(n.endswith("vbaProject.bin") for n in names):
        raise ValueError("检测到宏，默认拒收")
    if "word/encryption.xml" in names:
        raise ValueError("检测到加密，默认拒收")

    embedded = sum(1 for n in names if n.startswith("word/embeddings/"))
    if embedded > MAX_EMBEDDED_OBJECTS:
        raise ValueError(f"嵌入对象数超过 {MAX_EMBEDDED_OBJECTS} 限制")

    for info in _iter_zip_members(zf):
        if info.filename == "word/document.xml":
            content = zf.read(info)
            if _xml_depth(content) > MAX_XML_DEPTH:
                raise ValueError(f"XML 深度超过 {MAX_XML_DEPTH} 限制")


def _xml_depth(xml: bytes) -> int:
    depth = 0
    max_depth = 0
    i = 0
    n = len(xml)
    while i < n:
        if xml[i:i+1] == b"<":
            if xml[i+1:i+2] == b"/":
                depth -= 1
            elif xml[i+1:i+2] == b"!" or xml[i+1:i+2] == b"?":
                pass
            else:
                depth += 1
                max_depth = max(max_depth, depth)
            i = xml.find(b">", i)
        else:
            i += 1
    return max_depth


def validate_pdf(path: str) -> None:
    import pypdf
    try:
        reader = pypdf.PdfReader(path)
    except Exception as exc:
        raise ValueError("不是合法的 PDF 文件") from exc
    if reader.is_encrypted:
        raise ValueError("检测到加密，默认拒收")


@contextmanager
def resource_limits(cpu_seconds: int = 60, mem_bytes: int = 1024 * 1024 * 1024):
    """在当前进程设置 CPU 与内存软上限（仅 POSIX），退出时**必须还原**。

    RLIMIT_CPU 为进程累计 CPU 时间，不还原会杀死长驻 worker / 测试进程。
    """
    resource_module = None
    prev_cpu = prev_as = None
    try:
        import resource
        resource_module = resource
        prev_cpu = resource_module.getrlimit(resource_module.RLIMIT_CPU)
        prev_as = resource_module.getrlimit(resource_module.RLIMIT_AS)
        # 仅下调 soft limit；绝不能下调 hard limit，否则无特权进程无法恢复。
        cpu_hard = prev_cpu[1]
        as_hard = prev_as[1]
        cpu_soft = cpu_seconds if cpu_hard < 0 else min(cpu_seconds, cpu_hard)
        as_soft = mem_bytes if as_hard < 0 else min(mem_bytes, as_hard)
        resource_module.setrlimit(resource_module.RLIMIT_CPU, (cpu_soft, cpu_hard))
        resource_module.setrlimit(resource_module.RLIMIT_AS, (as_soft, as_hard))
    except (ImportError, ValueError, OSError):
        pass  # 非 POSIX / 无权限环境跳过
    try:
        yield
    finally:
        try:
            if resource_module is not None and prev_cpu is not None:
                resource_module.setrlimit(resource_module.RLIMIT_CPU, prev_cpu)
            if resource_module is not None and prev_as is not None:
                resource_module.setrlimit(resource_module.RLIMIT_AS, prev_as)
        except (ImportError, ValueError, OSError):
            pass


_SIGNATURES = {
    "docx": (b"PK\x03\x04",),
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),  # OLE2 复合文档
    "pdf": (b"%PDF",),
}


def check_file_signature(head: bytes, fmt: str) -> None:
    """扩展名与文件签名一致性校验（MVP §3.3 验收）。不匹配抛 ValueError。"""
    if fmt in _SIGNATURES:
        if not any(head.startswith(sig) for sig in _SIGNATURES[fmt]):
            raise ValueError(f"文件签名与扩展名 {fmt} 不匹配")
    elif fmt in ("txt", "csv", "json"):
        if b"\x00" in head:
            raise ValueError(f"文本文件 {fmt} 含二进制内容，签名不匹配")
    else:
        raise ValueError(f"不支持的简历格式: {fmt}")


def cleanup_tempdir(tempdir: str) -> None:
    import shutil
    shutil.rmtree(tempdir, ignore_errors=True)


class ParseSafetyError(Exception):
    """文件安全校验失败（加密/宏/压缩炸弹等），不可重试。"""
```

 - [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_safety.py -v`
预期：PASS

 - [x] **步骤 5：Commit**

```bash
git add backend/app/services/resume backend/tests/test_safety.py
git commit -m "feat: add resume file safety validation (P2 F6)"
```
---

### 任务 3：docx 双通道文本抽取 + pdf 文本层 + txt

**文件：**
- 创建：`backend/app/services/resume/extractor.py`
- 创建：`backend/app/services/resume/blocks.py`
- 测试：`backend/tests/test_extractor.py`

**验收（PRD F6 ②）：** docx 主力通道 = 正文段落 + 全部表格 + 文本框 XML 遍历（三通道），表格按行主序展平保留「标签:值」结构；pdf 文本层抽取；txt 直读；兜底通道接口（LibreOffice converter）保留，抽取器接口抽象。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_extractor.py
import pytest

from app.services.resume.blocks import Block, BlockKind
from app.services.resume.extractor import (
    DocxExtractor, PdfExtractor, TextExtractor, extract_resume,
)


def _build_docx_bytes() -> bytes:
    # 用 python-docx 构造：一个段落 + 一个表格（含「标签:值」）+ 一个文本框
    import io
    from docx import Document as Docx
    from docx.oxml import OxmlElement

    doc = Docx()
    doc.add_paragraph("张三个人简历")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "姓名"
    table.cell(0, 1).text = "张三"
    table.cell(1, 0).text = "电话"
    table.cell(1, 1).text = "13800000000"
    # 文本框：手工插入 w:txbxContent
    p = doc.add_paragraph()
    run = p.add_run()
    txbx = OxmlElement("w:txbxContent")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "文本框里的技能：Python"
    r.append(t)
    txbx.append(r)
    run._r.append(OxmlElement("w:drawing"))
    body = doc.element.body
    drawing = OxmlElement("w:drawing")
    drawing.insert(0, txbx)
    body.insert(0, drawing)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_docx_extract_contains_paragraph_and_table():
    data = _build_docx_bytes()
    blocks = DocxExtractor().extract(data)
    text = "\n".join(b.content for b in blocks)
    assert "张三个人简历" in text          # 段落通道
    assert "姓名" in text and "电话" in text  # 表格通道行主序
    # 表格行展平保留「标签:值」：至少含「姓名」与「张三」
    assert "张三" in text
    # 文本框通道（w:txbxContent XML 遍历）
    textbox_blocks = [b for b in blocks if b.kind == BlockKind.textbox]
    assert textbox_blocks and "Python" in textbox_blocks[0].content


def test_docx_extract_preserves_label_value_structure():
    data = _build_docx_bytes()
    blocks = DocxExtractor().extract(data)
    table_blocks = [b for b in blocks if b.kind == BlockKind.table]
    assert table_blocks, "应产出表格块"
    row_block = table_blocks[0].content
    assert "姓名" in row_block and "张三" in row_block


_MINIMAL_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]
   /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length 47 >>
stream
BT /F1 12 Tf 72 720 Td (PDF resume test) Tj ET
endstream
endobj
trailer
<< /Root 1 0 R /Size 6 >>
"""


def test_pdf_extract_text_layer(tmp_path):
    # 手工构造带 Helvetica 字体资源的最小 PDF
    # （pypdf 对「未注册字体资源 + 字面量内非 ASCII」的内容流无法可靠抽取，原写法测试必挂）
    path = tmp_path / "resume.pdf"
    path.write_bytes(_MINIMAL_PDF)
    blocks = PdfExtractor().extract(str(path))
    assert "PDF resume test" in "\n".join(b.content for b in blocks)


def test_text_extract():
    blocks = TextExtractor().extract("张三\n电话 13800000000")
    assert blocks[0].content == "张三"


def test_extract_resume_dispatch_by_format(tmp_path):
    (tmp_path / "a.txt").write_text("张三", encoding="utf-8")
    (tmp_path / "a.docx").write_bytes(_build_docx_bytes())
    p = tmp_path / "a.pdf"
    import pypdf
    w = pypdf.PdfWriter()
    w.add_blank_page(200, 200)
    with open(p, "wb") as f:
        w.write(f)
    assert extract_resume(str(tmp_path / "a.txt"), "txt")[0].content == "张三"
    assert extract_resume(str(tmp_path / "a.docx"), "docx")[0].kind == BlockKind.paragraph
    assert extract_resume(str(p), "pdf") is not None
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_extractor.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

 - [x] **步骤 3：创建块流模型与抽取器抽象**

```python
# backend/app/services/resume/blocks.py
import enum


class BlockKind(str, enum.Enum):
    paragraph = "paragraph"
    table = "table"
    textbox = "textbox"


class Block:
    __slots__ = ("kind", "content", "block_id")

    def __init__(self, kind: BlockKind, content: str, block_id: int):
        self.kind = kind
        self.content = content
        self.block_id = block_id

    def __repr__(self) -> str:
        return f"Block(kind={self.kind.value}, id={self.block_id}, content={self.content[:40]!r})"
```

```python
# backend/app/services/resume/extractor.py
import io
import os
import zipfile
from abc import ABC, abstractmethod
from xml.etree import ElementTree as ET

from app.services.resume.blocks import Block, BlockKind

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
W_DRAWING_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, source: str | bytes) -> list[Block]:
        ...


class _BlockCursor:
    def __init__(self):
        self._next = 0

    def next_id(self) -> int:
        self._next += 1
        return self._next


class DocxExtractor(BaseExtractor):
    """主力通道：python-docx 正文段落 + 全部表格 + 文本框 XML 遍历三通道。"""

    def extract(self, source: str | bytes) -> list[Block]:
        import docx

        data = source if isinstance(source, bytes) else open(source, "rb").read()
        doc = docx.Document(io.BytesIO(data))
        cursor = _BlockCursor()
        blocks: list[Block] = []

        # 通道 1：正文段落（含文本框字面量，按阅读顺序取自 body 中的 w:p）
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                blocks.append(Block(BlockKind.paragraph, text, cursor.next_id()))

        # 通道 2：全部表格——行主序展平，每行保留「单元格: 值」结构
        for table in doc.tables:
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append(Block(BlockKind.table, "\n".join(rows), cursor.next_id()))

        # 通道 3：文本框 XML 遍历（python-docx 不直接暴露文本框文本）
        for tb in _iter_textboxes(data):
            text = " ".join(tb.split())
            if text:
                blocks.append(Block(BlockKind.textbox, text, cursor.next_id()))

        return blocks


def _iter_textboxes(data: bytes) -> list[str]:
    """从 document.xml 中遍历所有 w:txbxContent 下的 w:t 文本。"""
    texts: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        return texts
    root = ET.fromstring(xml)
    for txbx in root.iter(W_NS + "txbxContent"):
        part = "".join(t.text or "" for t in txbx.iter(W_NS + "t"))
        if part.strip():
            texts.append(part.strip())
    return texts


class PdfExtractor(BaseExtractor):
    """pdf 文本层抽取（不做 OCR）。"""

    def extract(self, source: str | bytes) -> list[Block]:
        import pypdf

        stream = open(source, "rb") if isinstance(source, str) else io.BytesIO(source)
        reader = pypdf.PdfReader(stream)
        cursor = _BlockCursor()
        blocks = []
        for page in reader.pages:
            text = page.extract_text() or ""
            text = " ".join(text.split())
            if text:
                blocks.append(Block(BlockKind.paragraph, text, cursor.next_id()))
        return blocks


class TextExtractor(BaseExtractor):
    def extract(self, source: str | bytes) -> list[Block]:
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="ignore")
        else:
            with open(source, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        cursor = _BlockCursor()
        return [Block(BlockKind.paragraph, line.strip(), cursor.next_id())
                for line in text.splitlines() if line.strip()]


class LibreOfficeConverter:
    """兜底通道：soffice headless 转 docx 后重抽。资源受限（见 safety.resource_limits）。"""

    def convert(self, src_path: str, out_dir: str) -> str:
        import subprocess
        from app.services.resume.safety import resource_limits

        out_path = os.path.join(out_dir, os.path.basename(src_path).replace(".doc", ".docx"))
        cmd = ["soffice", "--headless", "--convert-to", "docx", "--outdir", out_dir, src_path]
        with resource_limits(cpu_seconds=60, mem_bytes=1024 * 1024 * 1024):
            result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0 or not os.path.exists(out_path):
            raise ValueError(f"LibreOffice 转换失败: {result.stderr.decode(errors='ignore')}")
        return out_path


def extract_resume(path: str, fmt: str) -> list[Block]:
    """按格式分派主力抽取；.doc 旧格式走 LibreOffice 兜底。"""
    if fmt == "docx":
        return DocxExtractor().extract(path)
    if fmt == "pdf":
        return PdfExtractor().extract(path)
    if fmt == "txt":
        return TextExtractor().extract(path)
    if fmt == "doc":
        converter = LibreOfficeConverter()
        converted = converter.convert(path, os.path.dirname(path))
        try:
            return DocxExtractor().extract(converted)
        finally:
            os.remove(converted)
    raise ValueError(f"不支持的简历格式: {fmt}")
```

 - [x] **步骤 4：在 pyproject.toml 增加依赖**

```toml
# backend/pyproject.toml [project].dependencies 追加
    "python-docx>=1.1",
    "pypdf>=4.0",
```

```bash
cd backend && uv pip install --system --group dev -e .
```

 - [x] **步骤 4b：Dockerfile 安装 LibreOffice headless（.doc 兜底通道，A-4）**

```dockerfile
# backend/Dockerfile：WORKDIR 之后、pip 安装之前追加（apt 层单独存放便于缓存）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*
```

> 本地开发环境若无法安装 soffice：.doc 抽取在运行期抛 `ValueError`（归类 `not_retryable`），测试一律 mock，不依赖真实 soffice（A-4 裁决）。

 - [x] **步骤 5：运行测试验证通过**

运行：`pytest backend/tests/test_extractor.py -v`
预期：PASS

 - [x] **步骤 6：Commit**

```bash
git add backend/app/services/resume backend/tests/test_extractor.py backend/pyproject.toml backend/Dockerfile
git commit -m "feat: add docx dual-channel and pdf text extraction (P2 F6)"
```

---

### 任务 4：Markdown IR 归一化与有效性校验

**文件：**
- 创建：`backend/app/services/resume/ir.py`
- 测试：`backend/tests/test_ir.py`

**验收（PRD F6 ③）：** 块流 → Resume Markdown IR（YAML 元数据头 + 章节式正文，表格保留 markdown 表格语法不展平）；IR 有效字符 < 200 判失败；IR 落库持久保存。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_ir.py
import pytest

from app.services.resume.blocks import Block, BlockKind
from app.services.resume.ir import IR_VALID_CHARS_THRESHOLD, build_ir, count_valid_chars, validate_ir


def test_build_ir_has_yaml_header():
    blocks = [
        Block(BlockKind.paragraph, "基本技能", 1),
        Block(BlockKind.table, "姓名 | 张三\n电话 | 13800000000", 2),
    ]
    ir = build_ir(blocks, source_channel="job_site", parser="docx/0.1", fmt="docx")
    assert "source_channel: job_site" in ir
    assert "parser: docx/0.1" in ir
    assert "| 姓名 | 张三 |" in ir or "姓名 | 张三" in ir


def test_count_valid_chars_ignores_whitespace():
    assert count_valid_chars("张 三\n\n  电话  ") == 4  # 张三电话


def test_validate_ir_below_threshold_fails():
    with pytest.raises(ValueError, match="有效字符"):  # noqa: SIM117
        validate_ir("a" * (IR_VALID_CHARS_THRESHOLD - 1))


def test_validate_ir_above_threshold_passes():
    validate_ir("好" * IR_VALID_CHARS_THRESHOLD)  # 不抛


def test_build_import_ir_from_structured_record():
    # PRD F6 ③：csv/json 结构化导入由字段生成 IR/检索文本，不做字符数阈值判定
    from app.services.resume.ir import build_import_ir
    record = {"name": "张三", "skills": ["Java", "Spring"],
              "work": [{"company": "A 公司", "title": "后端工程师", "content": "负责支付系统"}],
              "import_summary": {"education": "H 大学本科", "work": "A 公司 4 年"}}
    ir = build_import_ir(record, source_channel="referral")
    assert "source_channel: referral" in ir
    assert "A 公司" in ir and "负责支付系统" in ir
    assert "H 大学本科" in ir  # import_summary 供检索（schema spec §4）
    assert "Java" in ir
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_ir.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

 - [x] **步骤 3：实现 IR 归一化与校验**

```python
# backend/app/services/resume/ir.py
from datetime import datetime, timezone

from app.services.resume.blocks import Block, BlockKind

IR_VALID_CHARS_THRESHOLD = 200  # 与 PRD F6 / 评测 spec §2.5 冻结一致


def _yaml_header(source_channel: str, parser: str, fmt: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    return (
        "---\n"
        f"source_channel: {source_channel}\n"
        f"parser: {parser}\n"
        f"parse_time: {now}\n"
        f"format: {fmt}\n"
        "---\n"
    )


def _block_to_markdown(block: Block) -> list[str]:
    lines = [f"<!-- block_id: {block.block_id} kind: {block.kind.value} -->"]
    if block.kind is BlockKind.table:
        # 表格保留 markdown 表格语法：首行作为表头，表格不展平
        rows = block.content.split("\n")
        lines.append("| " + " | ".join(c.strip() for c in rows[0].split("|")) + " |")
        lines.append("|" + "|".join(["---"] * len(rows[0].split("|"))) + "|")
        for row in rows[1:]:
            lines.append("| " + " | ".join(c.strip() for c in row.split("|")) + " |")
    else:
        lines.append(block.content)
    return lines


def build_ir(blocks: list[Block], source_channel: str, parser: str, fmt: str) -> str:
    parts = [_yaml_header(source_channel, parser, fmt)]
    for block in blocks:
        parts.extend(_block_to_markdown(block))
        parts.append("")
    return "\n".join(parts)


def count_valid_chars(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def validate_ir(ir: str) -> None:
    if count_valid_chars(ir) < IR_VALID_CHARS_THRESHOLD:
        raise ValueError(f"IR 有效字符低于下限 {IR_VALID_CHARS_THRESHOLD}，抽取失败")


_ARRAY_LABELS = {"education": "教育经历", "work": "工作经历", "project": "项目经历"}


def build_import_ir(record: dict, source_channel: str) -> str:
    """csv/json 结构化导入的 IR：由结构化字段与 import_summary 生成（PRD F6 ③）。

    不走有效字符阈值判定（PRD：不以 JSON/CSV 语法字符数判断 IR 失败）。
    """
    lines = [
        "---",
        f"source_channel: {source_channel}",
        "parser: structured-import/0.1",
        f"parse_time: {datetime.now(timezone.utc).isoformat()}",
        "format: import",
        "---",
        "",
    ]
    for key, value in record.items():
        if value in (None, "", [], {}):
            continue
        if key == "import_summary":
            for part, text in value.items():
                if text:
                    lines.append(f"{part}: {text}")
        elif key in _ARRAY_LABELS:
            lines.append(f"## {_ARRAY_LABELS[key]}")
            for item in value:
                lines.append(" | ".join(str(v) for v in item.values() if v not in (None, "")))
        elif key == "skills":
            lines.append("技能: " + "、".join(value))
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)
```

 - [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_ir.py -v`
预期：PASS

 - [x] **步骤 5：Commit**

```bash
git add backend/app/services/resume/ir.py backend/tests/test_ir.py
git commit -m "feat: add resume markdown IR normalization and validation (P2 F6)"
```

---

### 任务 5：PII 识别与脱敏（LLM 出站前置）

**文件：**
- 创建：`backend/app/services/resume/pii.py`
- 修改：`backend/app/services/resume/__init__.py`（导出）
- 测试：`backend/tests/test_pii.py`

**验收（PRD F6 ④）：** 在任何外部模型调用之前执行；按 taxonomy 识别手机号/身份证/邮箱/姓名/地址/自由文本联系方式；识别失败、映射缺失或脱敏失败时 fail-closed，不发送请求；外发使用加密 token；全文索引/prompt/响应/trace 不得写入明文 PII。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_pii.py
import pytest

from app.services.resume.pii import (
    PIIType, identify_pii, desensitize_text, restore_pii_values, PIIRedactionError,
)


def test_identify_phone_and_email():
    spans = identify_pii("联系方式：13800000000 或 zhangsan@example.com")
    types = {s.pii_type for s in spans}
    assert types == {PIIType.phone, PIIType.email}
    assert spans[0].value == "13800000000"


def test_identify_id_card():
    spans = identify_pii("身份证号 110101199001011234")
    assert any(s.pii_type == PIIType.id_card for s in spans)


def test_identify_name_by_hint():
    # A-15：提示词式姓名（「姓名: X」）识别为 name 类 PII
    spans = identify_pii("姓名：张三 电话 13800000000")
    names = [s for s in spans if s.pii_type == PIIType.name]
    assert names and names[0].value == "张三"


def test_desensitize_replaces_with_token():
    masked, mapping = desensitize_text("电话 13800000000，邮箱 a@b.com")
    assert "13800000000" not in masked
    assert "a@b.com" not in masked
    assert mapping, "应返回映射"
    assert all(m.token and m.token.startswith("PII:") for m in mapping)


def test_desensitize_roundtrip_via_mapping():
    masked, mapping = desensitize_text("电话 13800000000")
    assert mapping[0].value == "13800000000"
    assert mapping[0].token in masked


def test_desensitize_is_deterministic():
    # evidence 引用脱敏后 IR（A-13）：同一输入重复脱敏结果必须一致，才可重放校验
    a, _ = desensitize_text("姓名：张三 电话 13800000000")
    b, _ = desensitize_text("姓名：张三 电话 13800000000")
    assert a == b


def test_restore_pii_values():
    masked, mapping = desensitize_text("电话 13800000000，邮箱 a@b.com")
    obj = {"phone": mapping[0].token, "email": mapping[1].token,
           "work": [{"content": f"联系 {mapping[0].token}"}], "city": None}
    restored = restore_pii_values(obj, mapping)
    assert restored["phone"] == "13800000000"
    assert restored["email"] == "a@b.com"
    assert "13800000000" in restored["work"][0]["content"]
    assert restored["city"] is None


def test_fail_closed_on_desensitize_error():
    # 孤立代理对无法编码为 UTF-8：脱敏必须抛 PIIRedactionError 而非静默放行
    with pytest.raises(PIIRedactionError):
        desensitize_text("\ud800")
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_pii.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

 - [x] **步骤 3：实现 PII 识别与脱敏**

```python
# backend/app/services/resume/pii.py
import enum
import hashlib
import re


class PIIType(str, enum.Enum):
    phone = "phone"
    email = "email"
    id_card = "id_card"
    name = "name"
    address = "address"


class PIIRedactionError(Exception):
    pass


class PIIMatch:
    __slots__ = ("pii_type", "value", "start", "end")

    def __init__(self, pii_type: PIIType, value: str, start: int, end: int):
        self.pii_type = pii_type
        self.value = value
        self.start = start
        self.end = end


class PIIMappingEntry:
    __slots__ = ("pii_type", "value", "token", "content_hash")

    def __init__(self, pii_type: PIIType, value: str, token: str):
        self.pii_type = pii_type
        self.value = value
        self.token = token
        self.content_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()


_PHONE_RE = re.compile(r"(?<![\d+])(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
# A-15：提示词式姓名（「姓名: 张三」/「Name: ...」）。姓名明文另落 candidates.name
# 供查重/展示（本地不出站），此处仅防止姓名随 IR 出站到外部模型。
_NAME_RE = re.compile(r"(?:姓名|名字|Name)\s*[:：]?\s*([\u4e00-\u9fa5]{2,4}|[A-Za-z][A-Za-z .]{1,48})")


def identify_pii(text: str) -> list[PIIMatch]:
    spans: list[PIIMatch] = []
    for matcher, pii_type in (
        (_PHONE_RE, PIIType.phone),
        (_EMAIL_RE, PIIType.email),
        (_ID_CARD_RE, PIIType.id_card),
    ):
        for m in matcher.finditer(text):
            spans.append(PIIMatch(pii_type, m.group(0), m.start(), m.end()))
    for m in _NAME_RE.finditer(text):
        spans.append(PIIMatch(PIIType.name, m.group(1), m.start(1), m.end(1)))
    return _resolve_overlaps(text, spans)


def _resolve_overlaps(text: str, spans: list[PIIMatch]) -> list[PIIMatch]:
    """重叠 span 合并为覆盖区间（防止丢弃 span 造成 PII 局部泄漏）。

    类型取非 name 优先（name 为宽松提示词匹配，phone/email/id_card 更精确）。
    """
    if not spans:
        return []
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    merged: list[PIIMatch] = [spans[0]]
    for span in spans[1:]:
        last = merged[-1]
        if span.start <= last.end:
            end = max(last.end, span.end)
            pii_type = last.pii_type if last.pii_type != PIIType.name else span.pii_type
            merged[-1] = PIIMatch(pii_type, text[last.start:end], last.start, end)
        else:
            merged.append(span)
    return merged


def _mask_with_token(text: str, spans: list[PIIMatch]) -> tuple[str, list[PIIMappingEntry]]:
    mapping: list[PIIMappingEntry] = []
    parts: list[str] = []
    cursor = 0
    for i, span in enumerate(spans):
        parts.append(text[cursor:span.start])
        token = f"PII:{span.pii_type.value}:{i}"
        mapping.append(PIIMappingEntry(span.pii_type, span.value, token))
        parts.append(token)
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts), mapping


def desensitize_text(text: str) -> tuple[str, list[PIIMappingEntry]]:
    """外发前调用。识别 + 脱敏任一失败即 fail-closed。"""
    try:
        text.encode("utf-8")  # 孤立代理对等无法安全序列化 → fail-closed
        spans = identify_pii(text)
        masked, mapping = _mask_with_token(text, spans)
        # 校验：明文值不得残留在输出中（fail-closed）
        for entry in mapping:
            if entry.value and entry.value in masked:
                raise PIIRedactionError(f"脱敏失败：明文残留 {entry.value}")
        return masked, mapping
    except (PIIRedactionError, UnicodeEncodeError, ValueError) as exc:
        raise PIIRedactionError(f"PII 脱敏失败，fail-closed: {exc}") from exc


def restore_pii_values(obj, mapping: list[PIIMappingEntry]):
    """LLM 输出中的 PII token 还原为明文（入库前调用，C-1 数据流闭环）。

    递归处理 dict/list/str；token 以整值替换与子串替换两种方式还原。
    """
    token_map = {entry.token: entry.value for entry in mapping}
    if not token_map:
        return obj

    def _restore(value):
        if isinstance(value, str):
            for token, plain in token_map.items():
                if token in value:
                    value = value.replace(token, plain)
            return value
        if isinstance(value, list):
            return [_restore(v) for v in value]
        if isinstance(value, dict):
            return {k: _restore(v) for k, v in value.items()}
        return value

    return _restore(obj)
```

 - [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_pii.py -v`
预期：PASS

 - [x] **步骤 5：Commit**

```bash
git add backend/app/services/resume/pii.py backend/tests/test_pii.py
git commit -m "feat: add PII identification and fail-closed redaction (P2 F6)"
```

---

### 任务 6：真实模型接入（embedding + LLM 经出站网关）

**文件：**
- 修改：`backend/app/services/outbound_gateway.py`
- 创建：`backend/app/services/model_client.py`
- 测试：`backend/tests/test_model_client.py`
- 不改：`backend/app/rag/embedder.py`（A-16）

**验收（PRD F6 ⑤ + deviation-log §4）：** 真实 bge-m3 embedding 与 deepseek-chat LLM 经 P1 出站网关（仅 HTTPS、禁私网、DNS 复检）调用，替换占位实现；PII 脱敏在出站之前（调用方保证）；失败分类 retryable/not_retryable。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_model_client.py
import pytest

from app.services.model_client import (
    LLMClient, EmbeddingClient, ModelCallError, classify_llm_error,
)
from app.services.resume.pii import desensitize_text


def _patch_post(monkeypatch, payload: dict):
    """将 outbound_gateway.http_post_json 替换为返回固定 payload。"""
    async def fake_post(url, headers, json, timeout=60.0):
        return payload
    monkeypatch.setattr("app.services.model_client.http_post_json", fake_post)


@pytest.mark.asyncio
async def test_embedding_client_returns_1024_dim(monkeypatch):
    _patch_post(monkeypatch, {"data": [{"index": 0, "embedding": [0.1] * 1024},
                                       {"index": 1, "embedding": [0.2] * 1024}]})
    client = EmbeddingClient(base_url="https://api.example.com/v1", api_key="sk-test")
    vecs = await client.embed(["你好", "世界"])
    assert len(vecs) == 2
    assert all(len(v) == 1024 for v in vecs)


@pytest.mark.asyncio
async def test_embedding_dimension_mismatch_is_not_retryable(monkeypatch):
    _patch_post(monkeypatch, {"data": [{"index": 0, "embedding": [0.1] * 512}]})
    client = EmbeddingClient(base_url="https://api.example.com/v1", api_key="sk-test")
    with pytest.raises(ModelCallError) as exc:
        await client.embed(["x"])
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_llm_client_json_call(monkeypatch):
    _patch_post(monkeypatch, {"choices": [{"message": {"content": '{"name": "张三"}'}}]})
    client = LLMClient(base_url="https://api.deepseek.com/v1", api_key="sk-test")
    out = await client.chat_json(system="你是解析器", user="解析简历", schema={"type": "object"})
    assert out == {"name": "张三"}


def test_classify_llm_error():
    assert classify_llm_error(TimeoutError()) is True        # 可重试
    assert classify_llm_error(ValueError("schema")) is False  # 不可重试
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_model_client.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

 - [x] **步骤 3：增强出站网关（https 调用 + 响应大小限制）**

```python
# backend/app/services/outbound_gateway.py 追加
import httpx

MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10MB

async def http_post_json(url: str, headers: dict, payload: dict, timeout: float = 60.0) -> dict:
    """生产出站调用统一入口：SSRF 校验 + 禁重定向 + 响应大小限制。"""
    await validate_endpoint(url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload, follow_redirects=False)
        raw = resp.content
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError(f"响应超过 {MAX_RESPONSE_BYTES} 限制")
        resp.raise_for_status()
        return resp.json()
```

 - [x] **步骤 4：实现模型客户端**

```python
# backend/app/services/model_client.py
from app.services.outbound_gateway import http_post_json

EMBEDDING_DIM = 1024


class ModelCallError(Exception):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def classify_llm_error(exc: Exception) -> bool:
    """返回 True 表示可重试（超时/限流/暂时网络错误）。"""
    text = str(exc).lower()
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if any(k in text for k in ("429", "timeout", "timed out", "temporarily", "rate limit", "503", "502")):
        return True
    return False


class EmbeddingClient:
    def __init__(self, base_url: str, api_key: str, model: str = "bge-m3"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            data = await http_post_json(url, headers, {"model": self.model, "input": texts})
        except Exception as exc:
            raise ModelCallError(f"embedding 调用失败: {exc}", retryable=classify_llm_error(exc)) from exc
        items = data.get("data", [])
        vecs = [item["embedding"] for item in sorted(items, key=lambda x: x.get("index", 0))]
        for v in vecs:
            if len(v) != EMBEDDING_DIM:
                raise ModelCallError(f"embedding 维度 {len(v)} != {EMBEDDING_DIM}", retryable=False)
        return vecs


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str = "deepseek-chat"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def chat_json(self, system: str, user: str, schema: dict) -> dict:
        """要求模型输出严格 JSON（response_format json_object）。"""
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            data = await http_post_json(url, headers, payload)
        except Exception as exc:
            raise ModelCallError(f"LLM 调用失败: {exc}", retryable=classify_llm_error(exc)) from exc
        content = data["choices"][0]["message"]["content"]
        import json
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelCallError("LLM 输出非合法 JSON", retryable=False) from exc
```

 - [x] **步骤 5：确认不改动 `app/rag/embedder.py`（A-16 裁决）**

P1 的 F5 chat 检索链路（`app/api/chat.py:177`）与 `tests/test_search.py::test_embedder_placeholder_returns_1024_dim` 依赖全局占位 embedder，且 KB chunks 目前为占位零向量——此时替换全局 embedder 会直接破坏 P1 回归。**简历流水线在任务 10 中直接使用 `EmbeddingClient`（workspace 级 model_config），不经过 `app/rag/embedder.py`。** KB 真实向量化随 F3 重解析留 P3，实现时记入 deviation-log。

验证：`pytest backend/tests/test_search.py backend/tests/test_chat.py -q` 保持 PASS（无代码改动）。

 - [x] **步骤 6：运行测试验证通过**

运行：`pytest backend/tests/test_model_client.py -v`
预期：PASS

 - [x] **步骤 7：Commit**

```bash
git add backend/app/services/outbound_gateway.py backend/app/services/model_client.py backend/tests/test_model_client.py
git commit -m "feat: integrate real embedding and LLM clients via outbound gateway (P2 F6)"
```

---

### 任务 7：两阶段 LLM 结构化（schema 输出 + evidence 校验 + 失败分类）

**文件：**
- 创建：`backend/app/services/resume/schema.py`
- 创建：`backend/app/services/resume/structured.py`
- 测试：`backend/tests/test_structured.py`

**验收（PRD F6 ⑤ + 评测 spec §6）：** 单次调用输出统一 Schema JSON；输出必须通过版本化 JSON Schema、类型/枚举/日期/长度/未知字段和 evidence 引用校验；校验失败重试一次后 failed；坏样本（不重试）vs 可重试分类；无法确定标 null，禁止编造。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_structured.py
import pytest

from app.services.resume.schema import SchemaValidationError, validate_candidate_json
from app.services.resume.structured import (
    extract_candidate, FailureClass, classify_failure,
)


def _valid_candidate() -> dict:
    return {
        "name": "张三",
        "gender": "男",
        "birth_month": "1995-03",
        "phone": "13800000000",
        "email": "zhangsan@example.com",
        "highest_degree": "本科",
        "city": "杭州",
        "expected_city": "杭州",
        "expected_position": "Java 后端",
        "skills": ["Java", "Spring"],
        "education": [{"school": "H 大学", "degree": "本科", "major": "计算机", "start": "2013-09", "end": "2017-06"}],
        "work": [{"company": "A 公司", "title": "后端工程师", "content": "负责支付系统", "start": "2017-07", "end": "2021-06", "type": "full_time"}],
        "project": [],
    }


def test_valid_candidate_passes():
    validate_candidate_json(_valid_candidate())


def test_unknown_enum_rejected():
    c = _valid_candidate()
    c["gender"] = "未知"
    with pytest.raises(SchemaValidationError):
        validate_candidate_json(c)


def test_bad_date_format_rejected():
    c = _valid_candidate()
    c["birth_month"] = "1995/03"
    with pytest.raises(SchemaValidationError):
        validate_candidate_json(c)


def test_too_long_field_rejected():
    c = _valid_candidate()
    c["name"] = "x" * 2001
    with pytest.raises(SchemaValidationError):
        validate_candidate_json(c)


def test_unknown_field_rejected():
    c = _valid_candidate()
    c["fabricated_field"] = "xxx"
    with pytest.raises(SchemaValidationError, match="未知字段"):
        validate_candidate_json(c)


def test_work_type_enum():
    c = _valid_candidate()
    c["work"][0]["type"] = "remote"
    with pytest.raises(SchemaValidationError):
        validate_candidate_json(c)


def test_classify_failure():
    assert classify_failure(SchemaValidationError("x")) is FailureClass.not_retryable
    assert classify_failure(TimeoutError()) is FailureClass.retryable
    assert classify_failure(ValueError("rate limit")) is FailureClass.retryable


_IR = ("---\nsource_channel: job_site\n---\n\n"
       "<!-- block_id: 1 kind: paragraph -->\n姓名：张三 电话 13800000000\n")


def _masked_block_text() -> str:
    # evidence 校验针对脱敏后 IR（A-13）；先重放脱敏拿到 block 文本与 token
    from app.services.resume.pii import desensitize_text
    masked, _ = desensitize_text("姓名：张三 电话 13800000000")
    return masked


@pytest.mark.asyncio
async def test_extract_candidate_restores_pii_and_verifies_evidence():
    block = _masked_block_text()          # 形如 "姓名：PII:name:0 电话 PII:phone:1"
    name_token = block.split("：")[1].split()[0]

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"candidate": {"name": name_token, "phone": "PII:phone:1"},
                    "evidence": {
                        "name": {"block_id": 1, "start_offset": 0,
                                 "end_offset": len(name_token), "quote": name_token},
                        "phone": {"block_id": 1, "start_offset": 0,
                                  "end_offset": len("PII:phone:1"), "quote": "PII:phone:1"},
                    }}

    out = await extract_candidate(FakeLLM(), _IR, "job_site")
    assert out.candidate["phone"] == "13800000000"      # token 已还原（C-1）
    ev = out.evidence["name"]
    assert ev["quote_hash"] and len(ev["quote_hash"]) == 16
    assert "quote" not in ev                              # 落库形态只留 hash（A-12/A-13）
    assert out.pii_mapping, "必须返回脱敏映射供入库持久化"


@pytest.mark.asyncio
async def test_extract_candidate_rejects_fabricated_evidence():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"candidate": {"name": "PII:name:0"},
                    "evidence": {"name": {"block_id": 1, "start_offset": 0,
                                           "end_offset": 4, "quote": "编造的引用"}}}

    with pytest.raises(SchemaValidationError):
        await extract_candidate(FakeLLM(), _IR, "job_site")
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_structured.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

 - [x] **步骤 3：实现版本化 Schema 校验**

```python
# backend/app/services/resume/schema.py
import re

RESUME_SCHEMA_VERSION = "resume/v1"

DEGREES = {"初中", "高中", "中专", "大专", "本科", "硕士", "博士"}
GENDERS = {"男", "女"}
WORK_TYPES = {"full_time", "intern", "part_time", "project"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PHONE_RE = re.compile(r"^\d{7,15}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

MAX_STR = 2000
MAX_ARRAY = 100

KNOWN_FIELDS = {
    "name", "gender", "birth_month", "phone", "email", "highest_degree",
    "hometown", "political_status", "expected_position", "city", "expected_city",
    "skills", "education", "work", "project",
}


class SchemaValidationError(Exception):
    pass


def _validate_common(record: dict) -> None:
    unknown = set(record) - KNOWN_FIELDS
    if unknown:
        raise SchemaValidationError(f"未知字段: {sorted(unknown)}")
    for k, v in record.items():
        if isinstance(v, str) and len(v) > MAX_STR:
            raise SchemaValidationError(f"字段 {k} 超长（>{MAX_STR}）")
    for k in ("name", "hometown", "political_status", "expected_position", "city", "expected_city"):
        if record.get(k) is not None and not isinstance(record[k], str):
            raise SchemaValidationError(f"字段 {k} 必须为字符串或 null")
    if record.get("gender") not in (None, "男", "女"):
        raise SchemaValidationError("gender 枚举非法")
    if record.get("highest_degree") is not None and record["highest_degree"] not in DEGREES:
        raise SchemaValidationError("highest_degree 枚举非法")
    for k in ("birth_month",):
        v = record.get(k)
        if v is not None and not MONTH_RE.match(v):
            raise SchemaValidationError(f"{k} 必须为 YYYY-MM")
    for k in ("city", "expected_city"):
        v = record.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > 128):
            raise SchemaValidationError(f"{k} 非法")
    if record.get("phone") is not None and not PHONE_RE.match(record["phone"]):
        raise SchemaValidationError("phone 格式非法")
    if record.get("email") is not None and not EMAIL_RE.match(record["email"]):
        raise SchemaValidationError("email 格式非法")


def _validate_dates(entry: dict, label: str) -> None:
    for k in ("start", "end"):
        v = entry.get(k)
        if v is not None and not MONTH_RE.match(v):
            raise SchemaValidationError(f"{label}.{k} 必须为 YYYY-MM 或 null")


def _validate_arrays(record: dict) -> None:
    for key, label in (("education", "education"), ("work", "work"), ("project", "project")):
        arr = record.get(key)
        if arr is None:
            continue
        if not isinstance(arr, list):
            raise SchemaValidationError(f"{key} 必须为数组")
        if len(arr) > MAX_ARRAY:
            raise SchemaValidationError(f"{key} 元素超过 {MAX_ARRAY}")
        for i, item in enumerate(arr):
            _validate_dates(item, f"{key}[{i}]")
        if key == "work":
            for i, item in enumerate(arr):
                if item.get("type") not in (None, "full_time", "intern", "part_time", "project"):
                    raise SchemaValidationError(f"work[{i}].type 枚举非法")
    if record.get("skills") is not None:
        if not isinstance(record["skills"], list) or len(record["skills"]) > MAX_ARRAY:
            raise SchemaValidationError("skills 必须为数组且 ≤100 项")
        for s in record["skills"]:
            if not isinstance(s, str) or len(s) > 200:
                raise SchemaValidationError("skills 元素非法")


def validate_candidate_json(candidate: dict) -> None:
    if not isinstance(candidate, dict) or not candidate:
        raise SchemaValidationError("candidate 必须为非空对象")
    _validate_common(candidate)
    _validate_arrays(candidate)
```

 - [x] **步骤 4：实现两阶段结构化编排**

```python
# backend/app/services/resume/structured.py
import enum
import hashlib
import re
from dataclasses import dataclass, field

from app.services.model_client import ModelCallError
from app.services.resume.pii import PIIMappingEntry, desensitize_text, restore_pii_values
from app.services.resume.schema import (
    KNOWN_FIELDS, RESUME_SCHEMA_VERSION, SchemaValidationError, validate_candidate_json,
)

RESUME_PROMPT_VERSION = "prompt/v1"

# 阶段一（结构识别）：A-1 裁决 P2 默认走单次调用（extract_candidate），
# 本接口保留供评测分类别 F1 不达标时启用两阶段。
STRUCTURE_SYSTEM_PROMPT = (
    "你是简历结构识别器。给定简历 Markdown，输出 JSON: {\"sections\": [...]}，"
    "每个 section 含 title 与 block_id 列表。"
)


class FailureClass(str, enum.Enum):
    not_retryable = "not_retryable"
    retryable = "retryable"


def classify_failure(exc: Exception) -> FailureClass:
    if isinstance(exc, SchemaValidationError):
        return FailureClass.not_retryable
    if isinstance(exc, ModelCallError):
        return FailureClass.retryable if exc.retryable else FailureClass.not_retryable
    text = str(exc).lower()
    if any(k in text for k in ("timeout", "429", "rate limit", "temporarily", "503", "502")):
        return FailureClass.retryable
    return FailureClass.not_retryable


@dataclass
class StructuredResult:
    candidate: dict
    evidence: dict = field(default_factory=dict)
    pii_mapping: list[PIIMappingEntry] = field(default_factory=list)


async def detect_structure(llm, ir: str) -> list:
    """阶段一（结构识别）保留接口（A-1）：评测分类别 F1 不达标时启用两阶段。"""
    masked_ir, _ = desensitize_text(ir)
    raw = await llm.chat_json(STRUCTURE_SYSTEM_PROMPT, f"<resume>\n{masked_ir}\n</resume>", {})
    return raw.get("sections") or []


EXTRACT_SYSTEM_PROMPT = f"""你是简历信息抽取器。输入简历 Markdown IR（PII 已替换为 PII:* token），输出严格 JSON（schema_version={RESUME_SCHEMA_VERSION}）。

规则：
1. 字段无法从简历确定时标 null，禁止编造。
2. 仅输出以下字段，不得输出未知字段: {', '.join(sorted(KNOWN_FIELDS))}
3. 时间格式 YYYY-MM；在职 end 为 null。
4. phone/email 等 PII 字段直接输出输入中的 PII:* token 原样，不得还原或改写。
5. 每个非 null 字段必须取自原文，并附 evidence 引用：
   {{"field_path": {{"block_id": 3, "start_offset": 5, "end_offset": 20, "quote": "IR 中逐字出现的引用串"}}}}
   quote 必须是输入 IR 对应 block 文本中逐字存在的子串（可为 PII token），不得编造引用。
输出 JSON 结构: {{"candidate": {{...}}, "evidence": {{field_path: {{block_id, start_offset, end_offset, quote}}}}}}"""

_BLOCK_MARKER_RE = re.compile(r"<!-- block_id: (\d+) kind: \w+ -->")


def parse_ir_blocks(ir: str) -> dict[int, str]:
    """解析 IR 的 block 标记，返回 block_id → block 文本（标记后到下一标记前）。"""
    blocks: dict[int, str] = {}
    matches = list(_BLOCK_MARKER_RE.finditer(ir))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(ir)
        blocks[int(m.group(1))] = ir[m.end():end].strip("\n")
    return blocks


def _verify_evidence(evidence: dict, masked_ir: str) -> dict:
    """A-13：quote 必须逐字出现在对应 block（脱敏后 IR）中，否则拒绝发布。

    offset 以 quote 实际出现位置为准（LLM offset 偏差时静默修正）；
    quote_hash 由系统计算（LLM 无法可靠计算 sha256）。
    """
    blocks = parse_ir_blocks(masked_ir)
    verified: dict = {}
    for field_path, ref in evidence.items():
        if not isinstance(ref, dict) or "block_id" not in ref or not ref.get("quote"):
            raise SchemaValidationError(f"evidence[{field_path}] 缺少 block_id 或 quote")
        block_text = blocks.get(int(ref["block_id"]))
        if block_text is None:
            raise SchemaValidationError(f"evidence[{field_path}] 引用了不存在的 block_id")
        quote = str(ref["quote"])
        pos = block_text.find(quote)
        if pos < 0:
            raise SchemaValidationError(f"evidence[{field_path}] 引用不存在于 IR（quote 未命中）")
        verified[field_path] = {
            "block_id": int(ref["block_id"]),
            "start_offset": pos,
            "end_offset": pos + len(quote),
            "quote_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest()[:16],
        }
    return verified


async def extract_candidate(llm, ir: str, source_channel: str) -> StructuredResult:
    """单次调用（A-1）：脱敏 → LLM → token 还原 → Schema 校验 → evidence 校验。

    evidence 只做「引用必须真实」的锚定校验（A-13），不做逐字段全覆盖——
    评测量化顺序：幻觉字段由评测 scorer（spec §4.3）阻断；全覆盖强制会因 LLM
    偶发漏引用把整份简历打成 not_retryable failed，压低 M3 成功率。
    """
    masked_ir, mapping = desensitize_text(ir)  # 出站前脱敏（双保险，fail-closed）
    raw = await llm.chat_json(EXTRACT_SYSTEM_PROMPT, f"<resume>\n{masked_ir}\n</resume>", {})
    candidate = raw.get("candidate")
    if not isinstance(candidate, dict):
        raise SchemaValidationError("LLM 输出缺少 candidate 对象")
    candidate = restore_pii_values(candidate, mapping)  # C-1：token → 明文后再校验/入库
    validate_candidate_json(candidate)
    evidence = _verify_evidence(raw.get("evidence") or {}, masked_ir)
    return StructuredResult(candidate=candidate, evidence=evidence, pii_mapping=mapping)
```

 - [x] **步骤 5：运行测试验证通过**

运行：`pytest backend/tests/test_structured.py -v`
预期：PASS

 - [x] **步骤 6：Commit**

```bash
git add backend/app/services/resume/schema.py backend/app/services/resume/structured.py backend/tests/test_structured.py
git commit -m "feat: add two-stage LLM structured extraction with schema and evidence validation (P2 F6)"
```

---

### 任务 8：AI 人才画像（固定八维 + 开放洞察）

**文件：**
- 创建：`backend/app/services/resume/profile.py`
- 测试：`backend/tests/test_profile.py`

**验收（PRD F6 ⑥）：** 第一层固定八维枚举（岗位中立）+ 第二层开放洞察（strengths/risks/career_pattern）；输出通过 JSON Schema 与 evidence 校验；无依据时生产字段返回 null；非法结果不得入库。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_profile.py
import pytest

from app.services.resume.profile import (
    PROFILE_SCHEMA_VERSION, ProfileResult, validate_profile_json, generate_profile,
    ProfileValidationError,
)


def _valid_profile() -> dict:
    return {
        "level": "Mid",
        "professional_depth": "Medium",
        "domain": "金融科技",
        "influence_scope": "个人贡献者",
        "management": "无",
        "stability": "正常",
        "growth_trend": "平稳",
        "communication": "中",
        "strengths": "熟悉支付系统",
        "risks": "稳定性一般",
        "career_pattern": "后端为主",
    }


def test_valid_profile_passes():
    validate_profile_json(_valid_profile())


def test_invalid_enum_rejected():
    p = _valid_profile()
    p["level"] = "SuperSenior"
    with pytest.raises(ProfileValidationError):
        validate_profile_json(p)


def test_null_enum_allowed():
    p = _valid_profile()
    p["level"] = None
    validate_profile_json(p)


@pytest.mark.asyncio
async def test_generate_profile_returns_null_on_no_evidence():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"profile": {"level": None}, "evidence": {}}

    result = await generate_profile(FakeLLM(), {"name": "张三"}, {})
    assert result.profile["level"] is None


@pytest.mark.asyncio
async def test_generate_profile_requires_candidate_evidence_for_non_null_conclusion():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"profile": {"level": "Mid"}, "evidence": {"level": ["work[0].content"]}}

    result = await generate_profile(FakeLLM(), {"work": [{"content": "支付系统"}]},
                                    {"work[0].content": {"block_id": 1}})
    assert result.evidence == {"level": ["work[0].content"]}


@pytest.mark.asyncio
async def test_generate_profile_prompt_excludes_pii():
    # 候选人对象此时已含还原后的明文 PII（C-1 流程），出站 prompt 必须剔除
    seen = {}

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            seen["user"] = user
            return {"profile": {"level": None}, "evidence": {}}

    await generate_profile(FakeLLM(), {"name": "张三", "phone": "13800000000",
                                       "email": "a@b.com", "city": "杭州"}, {})
    # A-15：phone/email/姓名均不出站（画像分析不需要身份字段）
    assert "13800000000" not in seen["user"]
    assert "a@b.com" not in seen["user"]
    assert "张三" not in seen["user"]
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_profile.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

 - [x] **步骤 3：实现画像 Schema 与生成**

```python
# backend/app/services/resume/profile.py
import json
from dataclasses import dataclass

from app.services.resume.pii import desensitize_text

PROFILE_SCHEMA_VERSION = "profile/v1"

LEVELS = {"Junior", "Mid", "Senior", "Staff", "Principal"}
DEPTHS = {"Low", "Medium", "High", "Expert"}
DOMAINS = {"金融科技", "电商", "AI", "医疗", "供应链"}
INFLUENCE = {"个人贡献者", "小组", "团队负责", "跨团队", "组织级"}
MANAGEMENT = {"无", "导师", "技术负责", "团队管理", "总监级"}
STABILITY = {"稳定", "正常", "频繁变动", "风险"}
GROWTH = {"上升", "平稳", "平台期", "下滑"}
COMMUNICATION = {"低", "中", "高"}

ENUM_FIELDS = {
    "level": LEVELS, "professional_depth": DEPTHS,
    "influence_scope": INFLUENCE, "management": MANAGEMENT,
    "stability": STABILITY, "growth_trend": GROWTH, "communication": COMMUNICATION,
}


class ProfileValidationError(Exception):
    pass


@dataclass
class ProfileResult:
    profile: dict
    evidence: dict


def validate_profile_json(profile: dict) -> None:
    if not isinstance(profile, dict):
        raise ProfileValidationError("profile 必须为对象")
    known = set(ENUM_FIELDS) | {"domain", "strengths", "risks", "career_pattern"}
    unknown = set(profile) - known
    if unknown:
        raise ProfileValidationError(f"profile 未知字段: {sorted(unknown)}")
    for field, allowed in ENUM_FIELDS.items():
        v = profile.get(field)
        if v is not None and v not in allowed:
            raise ProfileValidationError(f"profile.{field}={v!r} 非法枚举")
    # Schema spec §1.5：domain 为开放枚举，允许非空字符串（评测标签集另行冻结）。
    if profile.get("domain") is not None and (not isinstance(profile["domain"], str) or len(profile["domain"]) > 2000):
        raise ProfileValidationError("profile.domain 必须为字符串或 null")
    for k in ("strengths", "risks", "career_pattern"):
        v = profile.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > 2000):
            raise ProfileValidationError(f"profile.{k} 必须为字符串且 ≤2000")


PROFILE_SYSTEM_PROMPT = f"""你是人才画像分析师。基于候选人结构化信息输出八维固定画像 + 开放洞察。

八维枚举（必须严格使用，无法确定标 null，禁止编造）:
- level: {sorted(LEVELS)}
- professional_depth: {sorted(DEPTHS)}
- domain: {sorted(DOMAINS)}（开放枚举，可合理追加）
- influence_scope: {sorted(INFLUENCE)}
- management: {sorted(MANAGEMENT)}
- stability: {sorted(STABILITY)}
- growth_trend: {sorted(GROWTH)}
- communication: {sorted(COMMUNICATION)}
开放洞察: strengths / risks / career_pattern（自由文本，仅供 HR 阅读）

每个非 null 结论必须通过 evidence 引用至少一个候选人既有 evidence 字段路径；无依据返回 null。
输出 JSON: {{"profile": {{...}}, "evidence": {{"level": ["work[0].content"]}}}}"""


_PII_OUTBOUND_FIELDS = ("phone", "email", "name")  # A-15：身份/联系字段不出站


async def generate_profile(llm, candidate: dict, evidence: dict) -> ProfileResult:
    safe = {k: v for k, v in candidate.items() if k not in _PII_OUTBOUND_FIELDS}
    prompt, _ = desensitize_text(json.dumps({"candidate": safe}, ensure_ascii=False))
    raw = await llm.chat_json(PROFILE_SYSTEM_PROMPT, prompt, {})
    profile = raw.get("profile")
    if not isinstance(profile, dict):
        raise ProfileValidationError("LLM 输出缺少 profile 对象")
    validate_profile_json(profile)
    profile_evidence = raw.get("evidence") or {}
    non_null = {key for key, value in profile.items() if value is not None}
    if set(profile_evidence) != non_null:
        raise ProfileValidationError("画像非空字段必须逐项提供 evidence")
    for field, refs in profile_evidence.items():
        if not isinstance(refs, list) or not refs or any(ref not in evidence for ref in refs):
            raise ProfileValidationError(f"profile.{field} evidence 未引用候选人已有证据")
    return ProfileResult(profile=profile, evidence=profile_evidence)
```

 - [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_profile.py -v`
预期：PASS

 - [x] **步骤 5：Commit**

```bash
git add backend/app/services/resume/profile.py backend/tests/test_profile.py
git commit -m "feat: add AI talent profile generation with fixed eight-dimension enums (P2 F6)"
```

---

### 任务 9：查重、五段向量与入库

**文件：**
- 创建：`backend/app/services/resume/dedup.py`
- 创建：`backend/app/services/resume/derive.py`
- 创建：`backend/app/services/resume/segments.py`
- 创建：`backend/app/services/resume/ingest.py`
- 测试：`backend/tests/test_ingest.py`
- 测试：`backend/tests/test_derive.py`

**验收（PRD F6 ⑦ + F12 + MVP §3.3）：** PII 字段加密落库，手机/邮箱另存哈希供查重；姓名 +（phone 或 email）任一命中即重复，软删除记录仍参与；命中 → `pending_review` 不入 active；五段分层向量（摘要/教育/工作/项目/技能）；全文索引列。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_ingest.py
import pytest
from sqlalchemy import select

from app.services.resume.dedup import normalize_phone, normalize_email, hash_identity
from app.services.resume.segments import build_search_text, build_segments
from app.services.resume.ingest import search_duplicates


def test_normalize_phone():
    assert normalize_phone("+86 138 0000 0000") == "13800000000"
    assert normalize_phone("１３８００００００００") == "13800000000"  # 全角


def test_normalize_email():
    assert normalize_email("  Zhangsan@Example.COM ") == "zhangsan@example.com"


def test_hash_identity_consistent():
    assert hash_identity(normalize_phone("13800000000")) == hash_identity("13800000000")


def test_build_segments_all_five():
    candidate = {
        "name": "张三", "city": "杭州", "expected_position": "Java 后端",
        "skills": ["Java", "Spring"],
        "education": [{"school": "H 大学", "major": "计算机", "start": "2013-09", "end": "2017-06"}],
        "work": [{"company": "A 公司", "title": "后端工程师", "content": "负责支付系统", "start": "2017-07", "end": "2021-06"}],
        "project": [{"name": "支付平台", "responsibility": "核心开发"}],
    }
    segs = build_segments(candidate)
    assert set(segs) == {"summary", "education", "work", "project", "skills"}
    assert "支付系统" in segs["work"]
    assert "Java" in segs["skills"]
    # A-15：摘要段出站 embedding，不得含姓名/联系方式
    assert "张三" not in segs["summary"] and "138" not in segs["summary"]


def test_build_search_text_excludes_contact_pii_but_keeps_name_and_skills():
    candidate = {"name": "张三", "phone": "13800000000", "email": "a@b.com",
                 "city": "杭州", "skills": ["Java", "Spring"]}
    text = build_search_text(candidate)
    assert "13800000000" not in text and "a@b.com" not in text
    assert "张三" in text and "Java" in text  # 姓名/技能本地可检索


@pytest.mark.asyncio
async def test_search_duplicates_returns_matching_candidates():
    # 需要 DB：用 conftest 注入的 PG 库；先建 workspace 满足 FK
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="dup-owner@example.com", hashed_password="x", nickname="dup-owner")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="dup-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        db.add(Candidate(workspace_id=ws.id, status=CandidateStatus.active,
                         name="张三", phone_hash=hash_identity("13800000000"),
                         email_hash=hash_identity("zhangsan@example.com")))
        await db.commit()
        hits = await search_duplicates(db, ws.id, "张三", hash_identity("13800000000"), None)
        assert len(hits) >= 1
        assert hits[0].name == "张三"


@pytest.mark.asyncio
async def test_ingest_writes_real_vectors_pii_mapping_and_pending_review():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, PIIMapping, User, Workspace
    from app.services.resume.ingest import ingest
    from app.services.resume.pii import desensitize_text

    candidate = {"name": "王五", "phone": "13900000000", "email": "w@example.com",
                 "city": "杭州", "skills": ["Python"], "education": [], "work": [], "project": []}
    _, mappings = desensitize_text("姓名：王五 电话 13900000000 邮箱 w@example.com")
    async with SessionLocal() as db:
        owner = User(email="ingest-owner@example.com", hashed_password="x", nickname="owner")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="ingest-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        duplicate = Candidate(workspace_id=ws.id, status=CandidateStatus.active,
                              name="王五", phone_hash=hash_identity("13900000000"))
        db.add(duplicate)
        await db.flush()
        segments = build_segments(candidate)
        vectors = {name: [0.1] * 1024 for name, text in segments.items() if text.strip()}
        cand = await ingest(
            db, workspace_id=ws.id, run_id="run-ingest", revision_id="run-ingest:rev1",
            candidate=candidate, evidence={}, profile=None, ir_text="# 王五", ir_valid_chars=3,
            file_hash="f" * 64, storage_key="/tmp/record.json", fmt="json",
            content_type="application/json", file_size=1, duplicates=[duplicate],
            segments=segments, embeddings=vectors, pii_entries=mappings,
        )
        assert cand.status is CandidateStatus.pending_review
        assert cand.phone_enc and cand.phone_hash == hash_identity("13900000000")
        assert (await db.execute(select(PIIMapping).where(PIIMapping.run_id == "run-ingest"))).scalars().all()
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_ingest.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

 - [x] **步骤 3：实现查重归一化与匹配**

```python
# backend/app/services/resume/dedup.py
import hashlib

_FULL_TO_HALF = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９"}


def _to_half(text: str) -> str:
    return text.translate(_FULL_TO_HALF)


def normalize_phone(phone: str) -> str:
    p = _to_half(phone)
    p = p.replace("+86", "").replace(" ", "").replace("-", "")
    return p


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identity_hashes(name: str | None, phone: str | None, email: str | None) -> tuple[str | None, str | None]:
    phone_hash = hash_identity(normalize_phone(phone)) if phone else None
    email_hash = hash_identity(normalize_email(email)) if email else None
    return phone_hash, email_hash
```

 - [x] **步骤 4：实现五段向量构建**

```python
# backend/app/services/resume/segments.py
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
```

 - [x] **步骤 4b：实现派生字段与时间线 conflict 检测**

```python
# backend/app/services/resume/derive.py
from datetime import date


def derive_years_experience(candidate: dict, reference_date: date | None = None) -> int | None:
    """Schema spec §1.8：仅合并 full_time 闭区间，整年向下取整。"""
    reference_date = reference_date or date.today()
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


def detect_conflicts(candidate: dict) -> list[dict]:
    """P2 最小 conflict：同一候选人正式经历时间重叠，进入人工确认而不豁免评测。"""
    conflicts = []
    work = candidate.get("work") or []
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
```

```python
# backend/tests/test_derive.py
from datetime import date

from app.services.resume.derive import derive_years_experience, detect_conflicts


def test_years_experience_merges_overlapping_full_time_intervals():
    c = {"work": [
        {"type": "full_time", "start": "2020-01", "end": "2020-12"},
        {"type": "full_time", "start": "2020-06", "end": "2021-05"},
        {"type": "intern", "start": "2018-01", "end": "2019-12"},
    ]}
    assert derive_years_experience(c, date(2021, 5, 1)) == 1


def test_years_experience_uses_reference_date_for_current_job():
    c = {"work": [{"type": "full_time", "start": "2020-01", "end": None}]}
    assert derive_years_experience(c, date(2021, 1, 1)) == 1


def test_detect_conflicts_marks_overlapping_work():
    c = {"work": [
        {"start": "2020-01", "end": "2021-01"},
        {"start": "2020-06", "end": "2021-06"},
    ]}
    assert detect_conflicts(c)[0]["type"] == "timeline_overlap"
```

 - [x] **步骤 5：实现入库（候选人与 revision 写入）**

```python
# backend/app/services/resume/ingest.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Candidate, CandidateEmbedding, CandidateRevision, CandidateStatus,
    EmbeddingSegment, PIIMapping, PIIType, ResumeFile, ResumeIR,
)
from app.services.crypto import encrypt_secret
from app.services.resume.dedup import identity_hashes
from app.services.resume.segments import build_search_text


async def search_duplicates(db: AsyncSession, workspace_id: int, name: str, phone_hash: str | None, email_hash: str | None) -> list[Candidate]:
    if not (phone_hash or email_hash):
        return []
    from sqlalchemy import or_
    stmt = select(Candidate).where(
        Candidate.workspace_id == workspace_id,
        Candidate.status.in_(["active", "deleted", "pending_review"]),
        Candidate.name == name,
        or_(Candidate.phone_hash == phone_hash, Candidate.email_hash == email_hash),
    )
    return list((await db.execute(stmt)).scalars().all())


async def ingest(db: AsyncSession, *, workspace_id: int, run_id: str, revision_id: str,
                  candidate: dict, evidence: dict, profile: dict | None,
                  ir_text: str, ir_valid_chars: int, file_hash: str, storage_key: str,
                  fmt: str, content_type: str, file_size: int, duplicates: list[Candidate],
                  segments: dict[str, str], embeddings: dict[str, list[float]],
                  pii_entries: list | None = None,
                  conflicts: list[dict] | None = None) -> Candidate:
    """入库核心：同一 run 幂等（重复 run 不再写）。返回候选人。"""
    existing_rev = await db.execute(select(CandidateRevision).where(CandidateRevision.run_id == run_id))
    if existing_rev.scalar_one_or_none() is not None:
        raise RuntimeError(f"run {run_id} 已入库，幂等跳过")

    phone_hash, email_hash = identity_hashes(candidate.get("name"), candidate.get("phone"), candidate.get("email"))
    status = CandidateStatus.pending_review if duplicates else CandidateStatus.active
    # phone/email 只能进入 AES-GCM 列与 hash；CSV import_summary 不属于 candidate.json Schema，
    # 仅保留在 candidates.structured_data 并参与本地搜索/IR（schema spec §3.2/§4）。
    candidate_json = {k: v for k, v in candidate.items() if k not in {"phone", "email", "import_summary"}}
    stored_candidate = {**candidate_json}
    if candidate.get("import_summary"):
        stored_candidate["import_summary"] = candidate["import_summary"]
    cand = Candidate(
        workspace_id=workspace_id, status=status, name=candidate.get("name"),
        phone_enc=encrypt_secret(candidate["phone"]) if candidate.get("phone") else None,
        email_enc=encrypt_secret(candidate["email"]) if candidate.get("email") else None,
        phone_hash=phone_hash, email_hash=email_hash,
        structured_data=stored_candidate, search_text=build_search_text(stored_candidate),
    )
    db.add(cand)
    await db.flush()

    rev = CandidateRevision(candidate_id=cand.id, run_id=run_id, revision_id=revision_id,
                             candidate_json=candidate_json, profile_json=profile,
                             evidence=evidence, conflicts=conflicts or [])
    db.add(rev)
    await db.flush()
    cand.latest_revision_id = rev.id

    db.add(ResumeFile(run_id=run_id, candidate_id=cand.id, file_hash=file_hash,
                       storage_key=storage_key, format=fmt, file_size=file_size, content_type=content_type))
    db.add(ResumeIR(run_id=run_id, content=ir_text, valid_chars=ir_valid_chars))

    # C-1：脱敏映射需持久化，token 明文不写库，原始值仅 AES-GCM 加密保存。
    for entry in pii_entries or []:
        db.add(PIIMapping(run_id=run_id, pii_type=PIIType(entry.pii_type.value),
                          content_hash=entry.content_hash, token_enc=encrypt_secret(entry.value),
                          ir_locator={"token": entry.token}))

    for seg, text in segments.items():
        if text.strip():
            vector = embeddings.get(seg)
            if vector is None:
                raise ValueError(f"缺少 {seg} 段 embedding")
            db.add(CandidateEmbedding(candidate_id=cand.id, revision_id=revision_id,
                                      segment=EmbeddingSegment(seg), text=text, embedding=vector))
    # 不在此 commit：run.status=succeeded、候选人、revision、向量必须由 pipeline 同一事务提交。
    # 否则 worker 重启可看见已入库但仍 processing 的半完成 run。
    await db.flush()
    return cand
```

 - [x] **步骤 6：运行测试验证通过**

运行：`pytest backend/tests/test_ingest.py -v`
预期：PASS

 - [x] **步骤 7：Commit**

```bash
git add backend/app/services/resume/dedup.py backend/app/services/resume/derive.py backend/app/services/resume/segments.py backend/app/services/resume/ingest.py backend/tests/test_ingest.py backend/tests/test_derive.py
git commit -m "feat: add dedup, five-segment vectors and candidate ingest (P2 F6)"
```

---

### 任务 10：解析流水线编排（run 状态机 + 幂等 + 失败分类重试）

**文件：**
- 创建：`backend/app/services/resume/pipeline.py`
- 创建：`backend/app/services/audit.py`
- 创建：`backend/app/tasks/parse_resume.py`
- 修改：`backend/app/tasks/celery_app.py`
- 测试：`backend/tests/test_parse_resume.py`

**验收（PRD F6 幂等 + 失败分类 + deviation-log §4）：** Celery 至少一次投递 / worker 重启 / 重试不产生重复候选人、解析产物或索引写入；重试以 run_id 幂等、不重复扣费、不覆盖已发布版本；错误分类为不可重试（格式/安全/Schema）与可重试（超时/限流/网络），最多自动重试 2 次指数退避；连续失败进 dead-letter。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_parse_resume.py
import pytest

from app.services.resume.safety import ParseSafetyError
from app.services.resume.structured import FailureClass, classify_failure


def test_safety_error_is_not_retryable():
    assert classify_failure(ParseSafetyError("加密")) is FailureClass.not_retryable


def test_llm_timeout_is_retryable():
    assert classify_failure(TimeoutError()) is FailureClass.retryable


def test_pipeline_marks_short_ir_failed():
    # 不依赖 DB 的最小验证：IR 低于阈值直接 failed
    from app.services.resume.ir import IR_VALID_CHARS_THRESHOLD, validate_ir
    with pytest.raises(ValueError, match="有效字符"):
        validate_ir("短" * (IR_VALID_CHARS_THRESHOLD - 1))


@pytest.mark.asyncio
async def test_redis_lease_skips_duplicate_delivery(monkeypatch):
    from app.tasks import parse_resume as task_module

    class FakeRedis:
        async def set(self, *args, **kwargs):
            return False
        async def aclose(self):
            pass

    monkeypatch.setattr(task_module.Redis, "from_url", lambda *args, **kwargs: FakeRedis())
    client, should_execute = await task_module._acquire_lease("run-1")
    assert client is None and should_execute is False
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_parse_resume.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

 - [x] **步骤 3：实现 audit 事件写入**

```python
# backend/app/services/audit.py
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


async def add_event(db: AsyncSession, *, action: str, result: str = "success",
                    resource_type: str = "unknown", resource_id: str | None = None,
                    actor_id: int | None = None, workspace_id: int | None = None,
                    run_id: str | None = None, revision_id: str | None = None,
                    before_hash: str | None = None, after_hash: str | None = None,
                    request_id: str | None = None, correlation_id: str | None = None,
                    payload: dict | None = None) -> AuditEvent:
    """不可变审计事件：只追加。任何调用方不得 update/delete 已写入事件。"""
    evt = AuditEvent(
        event_id=str(uuid.uuid4()), request_id=request_id, correlation_id=correlation_id,
        actor_id=actor_id, workspace_id=workspace_id, resource_type=resource_type,
        resource_id=resource_id, action=action, result=result,
        before_hash=before_hash, after_hash=after_hash,
        run_id=run_id, revision_id=revision_id, payload=payload or {},
    )
    db.add(evt)
    return evt
```

 - [x] **步骤 4：实现流水线编排（run 状态机 + 幂等）**

```python
# backend/app/services/resume/pipeline.py
import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select

from app.models import ParseRun, ParseRunStatus
from app.services.model_client import EmbeddingClient, LLMClient, ModelCallError
from app.services.audit import add_event
from app.services.resume.derive import detect_conflicts, derive_years_experience
from app.services.resume.extractor import LibreOfficeConverter, extract_resume
from app.services.resume.ingest import ingest, search_duplicates
from app.services.resume.ir import (
    IR_VALID_CHARS_THRESHOLD,
    build_import_ir,
    build_ir,
    count_valid_chars,
    validate_ir,
)
from app.services.resume.pii import desensitize_text
from app.services.resume.profile import generate_profile
from app.services.resume.safety import (
    ParseSafetyError, check_file_signature, resource_limits, validate_docx_zip, validate_pdf,
)
from app.services.resume.schema import validate_candidate_json
from app.services.resume.segments import build_segments
from app.services.resume.structured import RESUME_PROMPT_VERSION, extract_candidate
from app.services.resume.dedup import identity_hashes


@dataclass
class PipelineOutcome:
    run_id: str
    status: ParseRunStatus
    candidate_id: int | None = None


def _sha256_json(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


async def _get_model_config(db, workspace_id: int, model_type: str):
    from app.models import ModelConfig
    row = await db.execute(select(ModelConfig).where(
        ModelConfig.workspace_id == workspace_id, ModelConfig.model_type == model_type))
    cfg = row.scalar_one_or_none()
    if cfg is None:
        raise ModelCallError(f"workspace 未配置 {model_type} 模型", retryable=False)
    return cfg


async def _get_llm(db, workspace_id: int) -> tuple[LLMClient, object]:
    from app.services.crypto import decrypt_secret

    cfg = await _get_model_config(db, workspace_id, "llm")
    return LLMClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name), cfg


async def _get_embedder(db, workspace_id: int) -> EmbeddingClient:
    from app.services.crypto import decrypt_secret

    cfg = await _get_model_config(db, workspace_id, "embedding")
    return EmbeddingClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


async def _embed_segments(db, workspace_id: int, candidate: dict) -> tuple[dict[str, str], dict[str, list[float]]]:
    """所有 embedding 前二次脱敏并去掉 identity PII（A-15）。"""
    raw_segments = build_segments(candidate)
    safe_segments = {name: desensitize_text(text)[0] for name, text in raw_segments.items() if text.strip()}
    nonempty = list(safe_segments.items())
    if not nonempty:
        return safe_segments, {}
    vectors = await (await _get_embedder(db, workspace_id)).embed([text for _, text in nonempty])
    if len(vectors) != len(nonempty):
        raise ModelCallError("embedding 返回数量与输入不一致", retryable=False)
    return safe_segments, dict(zip((name for name, _ in nonempty), vectors, strict=True))


def _stamp_evidence(evidence: dict, run_id: str) -> dict:
    return {path: {"ir_revision_id": run_id, **ref} for path, ref in evidence.items()}


def _content_type(fmt: str) -> str:
    return {
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "txt": "text/plain",
        "json": "application/json",
    }[fmt]


async def _run_import_pipeline(db, run: ParseRun, file_bytes: bytes) -> PipelineOutcome:
    """A-17：CSV/JSON 行级记录已结构化，跳过抽取阈值、LLM 与画像。"""
    try:
        payload = json.loads(file_bytes)
        record, meta = payload["record"], payload["meta"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ParseSafetyError(f"导入记录文件非法: {exc}") from exc
    validate_candidate_json({k: v for k, v in record.items() if k != "import_summary"})
    record["years_experience"] = derive_years_experience(record)
    conflicts = detect_conflicts(record)
    ir_text = build_import_ir(record, meta["source_channel"])
    _, pii_entries = desensitize_text(ir_text)  # 无 LLM 分支仍保存本地 PII 映射审计件
    run.ir_hash = hashlib.sha256(ir_text.encode("utf-8")).hexdigest()
    run.candidate_hash = _sha256_json(record)
    segments, vectors = await _embed_segments(db, run.workspace_id, record)
    phone_hash, email_hash = identity_hashes(record.get("name"), record.get("phone"), record.get("email"))
    duplicates = await search_duplicates(db, run.workspace_id, record.get("name") or "", phone_hash, email_hash)
    cand = await ingest(
        db, workspace_id=run.workspace_id, run_id=run.run_id, revision_id=f"{run.run_id}:rev1",
        candidate=record, evidence={}, profile=None, ir_text=ir_text, ir_valid_chars=count_valid_chars(ir_text),
        file_hash=run.file_hash, storage_key=run.file_path, fmt="json", content_type=_content_type("json"),
        file_size=run.file_size, duplicates=duplicates, segments=segments, embeddings=vectors,
        pii_entries=pii_entries, conflicts=conflicts,
    )
    run.status = ParseRunStatus.succeeded
    await add_event(db, action="parse.run.succeeded", resource_type="parse_run",
                    resource_id=run.run_id, workspace_id=run.workspace_id, run_id=run.run_id,
                    revision_id=f"{run.run_id}:rev1", after_hash=run.candidate_hash,
                    payload={"candidate_id": cand.id})
    await db.commit()
    return PipelineOutcome(run_id=run.run_id, status=run.status, candidate_id=cand.id)


async def run_pipeline(db, run: ParseRun, file_bytes: bytes) -> PipelineOutcome:
    """完整流水线：safety → extract → IR → LLM → profile → dedup → embedding → ingest。
    返回状态；异常由调用方（Celery 任务）按失败分类处理。"""
    run.status = ParseRunStatus.processing
    run.error_message = None
    await db.commit()

    if run.format == "json":
        return await _run_import_pipeline(db, run, file_bytes)

    try:
        check_file_signature(file_bytes[:8], run.format)
    except ValueError as exc:
        raise ParseSafetyError(str(exc)) from exc

    # 1) 文件安全（fail-closed：加密/宏/压缩炸弹 → ParseSafetyError，不可重试）
    if run.format == "docx":
        try:
            validate_docx_zip(file_bytes)
        except ValueError as exc:
            raise ParseSafetyError(str(exc)) from exc
    elif run.format == "pdf":
        try:
            validate_pdf(run.file_path)
        except ValueError as exc:
            raise ParseSafetyError(str(exc)) from exc

    # 2) 抽取（docx 三通道 / pdf 文本层 / txt；.doc 经 LibreOffice 兜底）
    with resource_limits(cpu_seconds=60, mem_bytes=1024 * 1024 * 1024):
        blocks = extract_resume(run.file_path, run.format)

    # PRD F6 ②：docx 主力通道低于阈值时，也要走 LibreOffice 兜底后重抽。
    ir_text = build_ir(blocks, run.source_channel, run.parser_version, run.format)
    if run.format == "docx" and count_valid_chars(ir_text) < IR_VALID_CHARS_THRESHOLD:
        try:
            converted = LibreOfficeConverter().convert(run.file_path, "/tmp")
            try:
                blocks = extract_resume(converted, "docx")
                ir_text = build_ir(blocks, run.source_channel, "libreoffice/0.1", run.format)
            finally:
                import os
                os.remove(converted)
        except ValueError:
            # soffice 不可用或转换失败：保留主力通道结果，随后由阈值失败归类 not_retryable。
            pass
    run.ir_hash = hashlib.sha256(ir_text.encode("utf-8")).hexdigest()
    validate_ir(ir_text)

    # 3) LLM 结构化（PII 在 extract_candidate 内 fail-closed 脱敏）+ 画像
    llm, llm_cfg = await _get_llm(db, run.workspace_id)
    run.llm_provider = urlparse(llm_cfg.base_url).hostname or llm_cfg.base_url
    run.llm_model = llm_cfg.model_name
    run.prompt_version = RESUME_PROMPT_VERSION
    run.schema_version = "resume/v1"
    structured = await extract_candidate(llm, ir_text, run.source_channel)
    structured.candidate["years_experience"] = derive_years_experience(structured.candidate)
    conflicts = detect_conflicts(structured.candidate)
    profile_result = await generate_profile(llm, structured.candidate, structured.evidence)
    profile = {"values": profile_result.profile, "evidence": profile_result.evidence}
    run.candidate_hash = _sha256_json(structured.candidate)
    run.profile_hash = _sha256_json(profile)

    # 4) 查重（命中 → pending_review，不入 active）+ 五段真实 embedding
    phone_hash, email_hash = identity_hashes(
        structured.candidate.get("name"), structured.candidate.get("phone"), structured.candidate.get("email"))
    duplicates = await search_duplicates(db, run.workspace_id,
                                         structured.candidate.get("name") or "", phone_hash, email_hash)
    segments, vectors = await _embed_segments(db, run.workspace_id, structured.candidate)

    # 5) 入库（同 run 幂等，见 ingest）
    revision_id = f"{run.run_id}:rev1"
    cand = await ingest(db, workspace_id=run.workspace_id, run_id=run.run_id, revision_id=revision_id,
                         candidate=structured.candidate, evidence=_stamp_evidence(structured.evidence, run.run_id), profile=profile,
                         ir_text=ir_text, ir_valid_chars=count_valid_chars(ir_text),
                         file_hash=run.file_hash, storage_key=run.file_path, fmt=run.format,
                         content_type=_content_type(run.format), file_size=run.file_size, duplicates=duplicates,
                         segments=segments, embeddings=vectors, pii_entries=structured.pii_mapping,
                         conflicts=conflicts)

    run.status = ParseRunStatus.succeeded
    await add_event(db, action="parse.run.succeeded", resource_type="parse_run",
                    resource_id=run.run_id, workspace_id=run.workspace_id, run_id=run.run_id,
                    revision_id=f"{run.run_id}:rev1", after_hash=run.candidate_hash,
                    payload={"candidate_id": cand.id})
    await db.commit()
    return PipelineOutcome(run_id=run.run_id, status=ParseRunStatus.succeeded, candidate_id=cand.id)
```

 - [x] **步骤 5：实现 Celery 任务（run 幂等 + 显式重试）**

```python
# backend/app/tasks/parse_resume.py
import asyncio
import logging

from celery import shared_task
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.models import FailureClass as FailureClassEnum
from app.models import ParseRun, ParseRunStatus
from app.services.audit import add_event
from app.services.resume.pipeline import run_pipeline
from app.services.resume.structured import FailureClass, classify_failure

logger = logging.getLogger(__name__)

MAX_AUTO_RETRIES = settings.resume_max_auto_retries
LEASE_SECONDS = 10 * 60


async def _acquire_lease(run_id: str) -> tuple[Redis | None, bool]:
    """A-18：Redis 为尽力互斥；不可用不阻断，DB 唯一约束仍是最终保障。"""
    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        if await client.set(f"resume:lease:{run_id}", "1", nx=True, ex=LEASE_SECONDS):
            return client, True
        await client.aclose()
        return None, False  # Redis 正常，但已有 worker 持有该 run 的 lease
    except Exception as exc:  # noqa: BLE001
        logger.warning("resume lease unavailable for %s: %s; falling back to DB idempotency", run_id, exc)
    return None, True         # Redis 不可用：继续，交给 DB 状态/唯一约束兜底


async def _release_lease(run_id: str, client: Redis | None) -> None:
    if client is None:
        return
    try:
        await client.delete(f"resume:lease:{run_id}")
    finally:
        await client.aclose()


async def _execute(run_id: str, retry_count: int) -> None:
    await engine.dispose()
    lease, should_execute = await _acquire_lease(run_id)
    if not should_execute:
        logger.info("run %s 已由其他 worker 持有 lease，跳过重复投递", run_id)
        return
    try:
        async with SessionLocal() as db:
            run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one_or_none()
            if run is None:
                return
            # 幂等：已终态不重复执行
            if run.status in (ParseRunStatus.succeeded, ParseRunStatus.failed, ParseRunStatus.dead_letter):
                logger.info("run %s 已终态 %s，跳过", run_id, run.status)
                return
            if run.status == ParseRunStatus.processing:
                # worker 重启 / 重复投递：processing 视为可安全重跑（入库幂等兜底）
                logger.warning("run %s 处于 processing，尝试重跑", run_id)
            run.retry_count = retry_count
            with open(run.file_path, "rb") as f:
                file_bytes = f.read()
            await run_pipeline(db, run, file_bytes)
    finally:
        await _release_lease(run_id, lease)
        await engine.dispose()


@shared_task(bind=True, max_retries=MAX_AUTO_RETRIES)
def parse_resume(self, run_id: str) -> None:
    try:
        asyncio.run(_execute(run_id, self.request.retries))
    except Exception as exc:  # noqa: BLE001
        retryable = classify_failure(exc) is FailureClass.retryable
        if retryable and self.request.retries < MAX_AUTO_RETRIES:
            countdown = 2 ** (self.request.retries + 1)  # 指数退避
            raise self.retry(exc=exc, countdown=countdown)
        # A-14：不可重试 → failed；可重试自动重试耗尽 → dead_letter。
        asyncio.run(_mark_terminal(run_id, exc, retryable))
        raise


async def _mark_terminal(run_id: str, exc: Exception, retryable: bool) -> None:
    async with SessionLocal() as db:
        run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one_or_none()
        if run is None:
            return
        if run.status == ParseRunStatus.succeeded:
            # 并发重复投递中另一 worker 已经提交成功，绝不能将其覆盖为失败终态。
            return
        run.status = ParseRunStatus.dead_letter if retryable else ParseRunStatus.failed
        run.failure_class = FailureClassEnum.retryable if retryable else FailureClassEnum.not_retryable
        run.error_message = str(exc)
        await add_event(db, action=f"parse.run.{run.status.value}", result="failure",
                        resource_type="parse_run", resource_id=run.run_id,
                        workspace_id=run.workspace_id, run_id=run.run_id,
                        payload={"failure_class": run.failure_class.value, "message": str(exc)})
        await db.commit()
```

 - [x] **步骤 6：注册任务并运行测试**

```python
# backend/app/core/config.py 追加
    resume_max_auto_retries: int = 2  # 生产最多自动重试 2 次；评测 manifest 运行时设 1（A-2）
```

```python
# backend/app/tasks/celery_app.py
celery_app = Celery("agentkb", broker=settings.redis_url, backend=settings.redis_url,
                    include=["app.tasks.parse_document", "app.tasks.parse_resume"])
```

```text
# backend/tests/conftest.py 注入默认（防止 env 缺失导致 settings 校验失败）
os.environ.setdefault("RESUME_MAX_AUTO_RETRIES", "2")
```

运行：`pytest backend/tests/test_parse_resume.py -v`
预期：PASS

 - [x] **步骤 7：Commit**

```bash
git add backend/app/services/resume/pipeline.py backend/app/services/audit.py backend/app/tasks/parse_resume.py backend/app/tasks/celery_app.py backend/app/core/config.py backend/tests/conftest.py backend/tests/test_parse_resume.py
git commit -m "feat: add resume parse pipeline orchestration with run idempotency and retry (P2 F6)"
```

---

### 任务 11：简历上传 / 导入 API（批量 + 进度 + 重试 + IR 查看）

**文件：**
- 创建：`backend/app/api/resumes.py`
- 创建：`backend/app/services/resume/importers.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_resumes_api.py`

**验收（PRD F6 ① + MVP §3.3）：** 批量上传 doc/docx/txt/csv/json（单次 ≤100 份、单份 ≤20MB）；csv/json 用 envelope（source_channel / template_version）；`workspace_id + upload_id` 幂等；单行错误不影响整批；失败可查看原因并单独重试（新 run_id）；批量进度；IR 审计产物可查看。

 - [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_resumes_api.py
import io

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_upload_resume_returns_runs(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "r@b.com", "password": "secret123", "nickname": "R"})
        token = (await c.post("/api/v1/auth/login", json={"email": "r@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        files = {"files": ("a.docx",  io.BytesIO(b"PK\x03\x04xx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/upload",
                         data={"upload_id": "up-1", "source_channel": "job_site"},
                         files=[("files", files["files"])], headers=h)
        assert r.status_code == 202
        assert r.json()["runs"]


@pytest.mark.asyncio
async def test_import_json_envelope(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "j@b.com", "password": "secret123", "nickname": "J"})
        token = (await c.post("/api/v1/auth/login", json={"email": "j@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        envelope = {
            "upload_id": "json-up-1",
            "schema_version": "resume-import/v1",
            "template_version": "2026-08-07.1",
            "source_channel": "referral",
            "referrer": "李四",
            "records": [{"name": "张三", "phone": "13800000000", "email": "a@b.com"}],
        }
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/import",
                         json=envelope, headers=h)
        assert r.status_code == 202
        assert "batch_id" in r.json() and len(r.json()["runs"]) == 1


@pytest.mark.asyncio
async def test_import_json_invalid_record_is_reported_without_aborting_batch(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "u@b.com", "password": "secret123", "nickname": "U"})
        token = (await c.post("/api/v1/auth/login", json={"email": "u@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        envelope = {
            "upload_id": "json-up-2",
            "schema_version": "resume-import/v1",
            "template_version": "2026-08-07.1",
            "source_channel": "referral",
            "records": [
                {"name": "张三", "fabricated_field": "x"},
                {"name": "李四", "skills": ["Python"]},
            ],
        }
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/import", json=envelope, headers=h)
        assert r.status_code == 202
        assert len(r.json()["runs"]) == 1
        assert r.json()["row_errors"] == [{"index": 0, "reason": "未知字段: ['fabricated_field']"}]


@pytest.mark.asyncio
async def test_upload_rejects_extension_signature_mismatch(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "m@b.com", "password": "secret123", "nickname": "M"})
        token = (await c.post("/api/v1/auth/login", json={"email": "m@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/upload",
                         data={"upload_id": "up-magic", "source_channel": "job_site"},
                         files=[("files", ("wrong.docx", io.BytesIO(b"%PDF-1.4"), "application/pdf"))], headers=h)
        assert r.status_code == 400
```

 - [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_resumes_api.py -v`
预期：FAIL，报错 404

 - [x] **步骤 3：实现 CSV/JSON 导入器**

```python
# backend/app/services/resume/importers.py
import csv
import hashlib
import io
import json
import os
import uuid

from app.services.resume.schema import KNOWN_FIELDS, validate_candidate_json

CSV_HEADERS = ["name", "gender", "birth_month", "phone", "email", "highest_degree",
               "city", "expected_city", "expected_position", "skills",
               "max_education_desc", "max_work_desc"]


class ResumeImportError(Exception):
    pass


def row_hash(row: dict) -> str:
    canonical = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_json_envelope(body: dict) -> tuple[dict, list[dict], list[dict]]:
    if not isinstance(body.get("upload_id"), str) or not body["upload_id"]:
        raise ResumeImportError("upload_id 批次级必填")
    if body.get("schema_version") != "resume-import/v1":
        raise ResumeImportError("schema_version 必须为 resume-import/v1")
    if not isinstance(body.get("template_version"), str) or not body["template_version"]:
        raise ResumeImportError("template_version 批次级必填")
    if not body.get("source_channel"):
        raise ResumeImportError("source_channel 批次级必填")
    records = body.get("records")
    if not isinstance(records, list) or not records:
        raise ResumeImportError("records 必须为非空数组")
    referrer = body.get("referrer")
    if referrer is not None and (not isinstance(referrer, str) or len(referrer) > 64):
        raise ResumeImportError("referrer 必须为字符串且 ≤64 字符")
    valid, errors = [], []
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            errors.append({"index": idx, "reason": "记录必须为对象"})
            continue
        if not rec.get("name"):
            errors.append({"index": idx, "reason": "name 为导入必填字段"})
            continue
        unknown = set(rec) - KNOWN_FIELDS
        if unknown:
            errors.append({"index": idx, "reason": f"未知字段: {sorted(unknown)}"})
            continue
        try:
            validate_candidate_json(rec)
        except Exception as exc:  # noqa: BLE001
            errors.append({"index": idx, "reason": str(exc)})
            continue
        valid.append(rec)
    return body, valid, errors


def parse_csv_bytes(data: bytes) -> tuple[list[dict], list[dict]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ResumeImportError("CSV 必须为 UTF-8 编码") from exc
    reader = csv.DictReader(io.StringIO(text), restkey="__extra__")
    if reader.fieldnames != CSV_HEADERS or len(set(reader.fieldnames or [])) != len(CSV_HEADERS):
        raise ResumeImportError(f"CSV 表头必须为固定列序: {CSV_HEADERS}")
    rows, errors = [], []
    for line_no, row in enumerate(reader, start=2):
        if row.pop("__extra__", None):
            errors.append({"row_no": line_no, "reason": "CSV 列数超过固定表头"})
            continue
        if row.get("skills"):
            row["skills"] = row["skills"].split(";")
        # 空串 → None
        row = {k: (None if v == "" else v) for k, v in row.items()}
        record = {k: row.get(k) for k in KNOWN_FIELDS if k in row}
        record["education"] = record["work"] = record["project"] = None
        if not record.get("name"):
            errors.append({"row_no": line_no, "reason": "name 为导入必填字段"})
            continue
        try:
            validate_candidate_json(record)
        except Exception as exc:  # noqa: BLE001
            errors.append({"row_no": line_no, "reason": str(exc)})
            continue
        record["import_summary"] = {
            "education": row.get("max_education_desc"),
            "work": row.get("max_work_desc"),
        }
        rows.append({"row_no": line_no, "row_hash": row_hash(record), "data": record})
    return rows, errors


def write_record_file(upload_dir: str, workspace_id: int, record: dict, meta: dict) -> tuple[str, int]:
    """A-17：每个导入记录落独立 JSON 文件，供 1 run : 1 candidate 幂等消费。"""
    payload = json.dumps({"record": record, "meta": meta}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path = os.path.join(upload_dir, f"{workspace_id}-import-{uuid.uuid4().hex}.json")
    with open(path, "wb") as out:  # noqa: ASYNC230
        out.write(payload)
    return path, len(payload)
```

 - [x] **步骤 4：实现上传 / 导入 / 进度 / 重试 / IR 端点**

```python
# backend/app/api/resumes.py
import hashlib
import json
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import ParseRun, ParseRunStatus, User
from app.services.kb_service import ensure_member
from app.services.resume.importers import (
    ResumeImportError,
    parse_csv_bytes,
    parse_json_envelope,
    row_hash,
    write_record_file,
)
from app.services.resume.safety import check_file_signature
from app.tasks.parse_resume import parse_resume

router = APIRouter(prefix="/api/v1", tags=["resumes"])

ALLOWED_FORMATS = {"doc", "docx", "pdf", "txt", "csv", "json"}
ALLOWED_CHANNELS = {"referral", "job_site", "headhunter", "campus", "other"}
ALLOWED_CONTENT_TYPES = {
    "doc": {"application/msword", "application/octet-stream"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "pdf": {"application/pdf"},
    "txt": {"text/plain"},
    "csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
    "json": {"application/json"},
}
MAX_FILES = 100
MAX_FILE_SIZE = 20 * 1024 * 1024
UPLOAD_DIR = os.environ.get("RESUME_UPLOAD_DIR", "/tmp/resume_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _fmt_from_filename(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    if ext not in ALLOWED_FORMATS:
        raise HTTPException(400, f"不支持的简历格式: {ext}")
    return ext


async def _create_run(db: AsyncSession, *, workspace_id: int, upload_id: str, source_channel: str,
                      fmt: str, file_path: str, file_size: int, file_hash: str,
                      template_version: str | None = None, referrer: str | None = None) -> ParseRun:
    run = ParseRun(run_id=str(uuid.uuid4()), workspace_id=workspace_id, upload_id=upload_id,
                   source_channel=source_channel, template_version=template_version, referrer=referrer,
                   format=fmt, file_hash=file_hash, file_path=file_path, file_size=file_size,
                   parser_version="0.1.0", status=ParseRunStatus.pending)
    db.add(run)
    return run


async def _read_limited(upload: UploadFile) -> bytes:
    if upload.size is not None and upload.size > MAX_FILE_SIZE:
        raise HTTPException(413, f"文件超过 {MAX_FILE_SIZE} 限制")
    parts, total = [], 0
    while part := await upload.read(1024 * 1024):
        total += len(part)
        if total > MAX_FILE_SIZE:
            raise HTTPException(413, f"文件超过 {MAX_FILE_SIZE} 限制")
        parts.append(part)
    return b"".join(parts)


async def _save_record_run(db: AsyncSession, *, ws_id: int, upload_id: str, source_channel: str,
                           record: dict, template_version: str | None, referrer: str | None) -> ParseRun:
    path, file_size = write_record_file(
        UPLOAD_DIR, ws_id, record,
        {"source_channel": source_channel, "template_version": template_version, "referrer": referrer},
    )
    return await _create_run(
        db, workspace_id=ws_id, upload_id=upload_id, source_channel=source_channel,
        fmt="json", file_path=path, file_size=file_size, file_hash=row_hash(record),
        template_version=template_version, referrer=referrer,
    )


@router.post("/workspaces/{ws_id}/resumes/upload", status_code=202)
async def upload_resumes(ws_id: int, upload_id: str = Form(...), source_channel: str = Form(...),
                          template_version: str | None = Form(None),
                          files: list[UploadFile] = File(...),
                         user: User = Depends(get_current_user),  # noqa: B008
                         db: AsyncSession = Depends(get_db)):   # noqa: B008
    await ensure_member(db, ws_id, user.id)
    if source_channel not in ALLOWED_CHANNELS:
        raise HTTPException(400, f"非法 source_channel: {source_channel}")
    if not upload_id:
        raise HTTPException(400, "缺少 upload_id")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"单次上传不超过 {MAX_FILES} 份")
    # upload_id 幂等：同 (ws, upload_id) 已存在 run 则返回既有 run 列表
    existing = (await db.execute(select(ParseRun).where(
        ParseRun.workspace_id == ws_id, ParseRun.upload_id == upload_id))).scalars().all()
    if existing:
        return {"batch_id": upload_id, "runs": [r.run_id for r in existing], "duplicate": True}

    # 先完整读入并校验整批，避免第 N 个文件失败时前 N-1 已经 commit 的半批状态。
    prepared = []
    for f in files:
        fmt = _fmt_from_filename(f.filename or "")
        if (f.content_type or "") not in ALLOWED_CONTENT_TYPES[fmt]:
            raise HTTPException(400, "文件扩展名与 Content-Type 不匹配")
        head = await f.read(8)
        await f.seek(0)
        try:
            check_file_signature(head, fmt)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        content = await _read_limited(f)
        prepared.append((f.filename or "", fmt, content))

    runs, row_errors = [], []
    for filename, fmt, content in prepared:
        if fmt == "json":
            try:
                meta, records, json_errors = parse_json_envelope(json.loads(content))
            except (ResumeImportError, json.JSONDecodeError) as exc:
                raise HTTPException(400, f"JSON envelope 非法: {exc}") from exc
            if meta["source_channel"] != source_channel:
                raise HTTPException(400, "multipart source_channel 必须与 JSON envelope 一致")
            row_errors.extend(json_errors)
            for record in records:
                run = await _save_record_run(
                    db, ws_id=ws_id, upload_id=upload_id, source_channel=source_channel,
                    record=record, template_version=meta.get("template_version"),
                    referrer=meta.get("referrer"),
                )
                runs.append(run)
            continue
        if fmt == "csv":
            if not template_version:
                raise HTTPException(400, "CSV 导入必须提供 template_version")
            try:
                rows, csv_errors = parse_csv_bytes(content)
            except ResumeImportError as exc:
                raise HTTPException(400, str(exc)) from exc
            row_errors.extend(csv_errors)
            for row in rows:
                run = await _save_record_run(
                    db, ws_id=ws_id, upload_id=upload_id, source_channel=source_channel,
                    record=row["data"], template_version=template_version, referrer=None,
                )
                runs.append(run)
            continue
        file_hash = hashlib.sha256(content).hexdigest()
        safe_name = os.path.basename(filename)
        storage_key = os.path.join(UPLOAD_DIR, f"{ws_id}-{uuid.uuid4().hex}-{safe_name}")
        with open(storage_key, "wb") as out:
            out.write(content)
        run = await _create_run(db, workspace_id=ws_id, upload_id=upload_id, source_channel=source_channel,
                                fmt=fmt, file_path=storage_key, file_size=len(content), file_hash=file_hash)
        runs.append(run)
    await db.commit()
    for run in runs:
        await db.refresh(run)
        parse_resume.delay(run.run_id)
    return {"batch_id": upload_id, "runs": [run.run_id for run in runs],
            "row_errors": row_errors, "duplicate": False}


@router.post("/workspaces/{ws_id}/resumes/import", status_code=202)
async def import_resumes(ws_id: int, body: dict, user: User = Depends(get_current_user),  # noqa: B008
                         db: AsyncSession = Depends(get_db)):  # noqa: B008
    await ensure_member(db, ws_id, user.id)
    try:
        meta, records, row_errors = parse_json_envelope(body)
    except ResumeImportError as exc:
        raise HTTPException(400, str(exc)) from exc
    batch_id = meta["upload_id"]
    existing = (await db.execute(select(ParseRun).where(
        ParseRun.workspace_id == ws_id, ParseRun.upload_id == batch_id))).scalars().all()
    if existing:
        return {"batch_id": batch_id, "runs": [run.run_id for run in existing],
                "row_errors": [], "duplicate": True}
    runs = []
    for rec in records:
        run = await _save_record_run(
            db, ws_id=ws_id, upload_id=batch_id, source_channel=meta["source_channel"], record=rec,
            template_version=meta.get("template_version"), referrer=meta.get("referrer"),
        )
        runs.append(run)
    await db.commit()
    for run in runs:
        await db.refresh(run)
        parse_resume.delay(run.run_id)
    return {"batch_id": batch_id, "runs": [run.run_id for run in runs], "row_errors": row_errors}


@router.get("/workspaces/{ws_id}/resumes/runs")
async def list_runs(ws_id: int, page: int = 1, page_size: int = 20,
                    user: User = Depends(get_current_user),  # noqa: B008
                    db: AsyncSession = Depends(get_db)):  # noqa: B008
    await ensure_member(db, ws_id, user.id)
    page, page_size = max(1, page), max(1, min(page_size, 100))
    total = await db.scalar(select(func.count(ParseRun.id)).where(ParseRun.workspace_id == ws_id))
    rows = await db.execute(select(ParseRun).where(ParseRun.workspace_id == ws_id)
                            .order_by(ParseRun.id.desc()).offset((page - 1) * page_size).limit(page_size))
    items = [{"run_id": r.run_id, "format": r.format, "status": r.status.value,
              "source_channel": r.source_channel, "created_at": r.created_at.isoformat(),
              "error_message": r.error_message} for r in rows.scalars().all()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/resume-runs/{run_id}")
async def get_run(run_id: str, user: User = Depends(get_current_user),  # noqa: B008
                  db: AsyncSession = Depends(get_db)):  # noqa: B008
    run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "资源不存在")
    await ensure_member(db, run.workspace_id, user.id)
    return {"run_id": run.run_id, "status": run.status.value, "failure_class": run.failure_class.value if run.failure_class else None,
            "retry_count": run.retry_count, "error_message": run.error_message,
            "ir_hash": run.ir_hash, "candidate_hash": run.candidate_hash, "profile_hash": run.profile_hash}


@router.get("/resume-runs/{run_id}/ir")
async def get_run_ir(run_id: str, user: User = Depends(get_current_user),  # noqa: B008
                     db: AsyncSession = Depends(get_db)):  # noqa: B008
    from app.models import ResumeIR
    run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "资源不存在")
    await ensure_member(db, run.workspace_id, user.id)
    ir = (await db.execute(select(ResumeIR).where(ResumeIR.run_id == run_id))).scalar_one_or_none()
    if ir is None:
        raise HTTPException(404, "IR 产物不存在")
    return {"run_id": run_id, "content": ir.content, "valid_chars": ir.valid_chars}


@router.post("/resume-runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: str, user: User = Depends(get_current_user),  # noqa: B008
                    db: AsyncSession = Depends(get_db)):  # noqa: B008
    run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "资源不存在")
    await ensure_member(db, run.workspace_id, user.id)
    if run.status not in (ParseRunStatus.failed, ParseRunStatus.dead_letter):
        raise HTTPException(409, "仅失败状态的 run 可重试")
    # 人工 retry 生成新 run_id（PRD：人工 retry 生成新的 run_id，不覆盖已发布 revision）
    new_run = ParseRun(run_id=str(uuid.uuid4()), workspace_id=run.workspace_id, upload_id=run.upload_id,
                       source_channel=run.source_channel, template_version=run.template_version, referrer=run.referrer,
                       format=run.format, file_hash=run.file_hash, file_path=run.file_path,
                       file_size=run.file_size, parser_version=run.parser_version, status=ParseRunStatus.pending)
    db.add(new_run)
    await db.commit()
    await db.refresh(new_run)
    parse_resume.delay(new_run.run_id)
    return {"run_id": new_run.run_id, "status": "pending"}
```

 - [x] **步骤 5：注册路由**

```python
# backend/app/main.py 追加
from app.api import resumes
app.include_router(resumes.router)
```

> `backend/tests/conftest.py` 的清理表已在**任务 1**迁移应用后更新；此处不要重复移动，避免任务 9 的 PG 测试在新表出现前运行。

 - [x] **步骤 6：运行测试验证通过**

运行：`pytest backend/tests/test_resumes_api.py -v`
预期：PASS

 - [x] **步骤 7：Commit**

```bash
git add backend/app/api/resumes.py backend/app/services/resume/importers.py backend/app/main.py backend/tests/test_resumes_api.py
git commit -m "feat: add resume upload, import, progress, retry and IR endpoints (P2 F6)"
```

---

## 自检

**1. 规格覆盖度：**

| 需求 | 对应任务 |
|------|---------|
| PRD F6 ① 批量上传（≤100 份/≤20MB，envelope source_channel） | 任务 11 |
| PRD F6 ② 双通道抽取（docx 段落+表格+文本框、pdf 文本层、.doc / 低有效字符 docx 兜底） | 任务 3、10 |
| PRD F6 ③ Markdown IR + 有效性校验（≥200 字符；结构化导入不以阈值拒绝） | 任务 4、10 |
| PRD F6 ④ PII 识别与脱敏前置（fail-closed；token 还原后加密落库） | 任务 5、7、9、10 |
| PRD F6 ⑤ 两阶段 LLM 结构化（Schema + quote/evidence 校验，null 不编造） | 任务 7 |
| PRD F6 ⑥ AI 人才画像（八维 + 开放洞察） | 任务 8 |
| PRD F6 ⑦ 入库（PII 加密、查重哈希、五段向量、全文索引） | 任务 9、10 |
| 解析审计链（run_id/revision/产物 hash/版本/evidence/不可变事件） | 任务 1、7、9、10、11 |
| 文件解析安全（宏/加密/压缩炸弹/资源上限/扩展名-MIME-签名一致） | 任务 2、11 |
| 幂等与可重跑（Redis lease + DB revision 唯一 + 状态检查；CSV/JSON row_hash） | 任务 10、11 |
| 失败分类与重试（not_retryable/retryable，最多 2 次指数退避，dead-letter） | 任务 7、10 |
| 查重（姓名 + phone/email 精确，软删除参与，pending_review） | 任务 9 |
| 真实 embedding/LLM 经出站网关（deviation-log §4；简历域五段实时向量） | 任务 6、10 |
| 不可变审计事件（deviation-log §4） | 任务 1、10 |
| run 表 / 画像表 / 解析审计表 / PII 处理模块（新表新服务） | 任务 1、5、9、10 |
| CSV/JSON 导入契约（schema spec §3；record 文件、逐行错误、referrer、upload_id） | 任务 4、10、11 |
| years_experience 闭区间派生 + timeline conflict | 任务 9、10 |

**2. 完整性扫描：** 所有步骤均有具体文件、代码、命令和预期结果；`.doc` LibreOffice 兜底在测试环境用 mock 路径（任务 3 已注明）；`ingest` **不允许**写占位向量，任务 10 必须从 workspace embedding model_config 取得真实 1024 维向量后才可入库。A-16 明确保留 P1 的 `rag/embedder.py` 占位，仅简历领域走真实 embedding。画像第三层（Candidate×Job）明确留 P3（A-11）。

**3. 类型一致性：**
- `ParseRunStatus` / `FailureClass` / `ParseSafetyError` 在任务 1/2/10 定义与引用一致。
- `extract_candidate(llm, ir, source_channel)` → `StructuredResult(candidate, evidence, pii_mapping)`；`generate_profile(llm, candidate, evidence)` → `ProfileResult(profile, evidence)`；`ingest(..., segments, embeddings, pii_entries, conflicts)` 的所有调用在任务 9/10 一致。
- `classify_failure(exc)` 在任务 7 定义、任务 10 Celery 复用。
- `search_duplicates(db, ws_id, name, phone_hash, email_hash)` 在任务 9/10 一致。
- `identity_hashes(name, phone, email)` 返回 `(phone_hash, email_hash)`，任务 9/10 一致。

**4. 安全复核（PRD v0.26 对齐）：**
 - [x] PII 在任何外部模型调用前脱敏（任务 5 token 映射 + 任务 7 LLM + 任务 8 profile 字段剔除 + 任务 10 embedding 二次脱敏）
 - [x] 出站仅 HTTPS、禁私网（复用 P1 outbound_gateway，任务 6）
 - [x] 文件安全 fail-closed（宏/加密/压缩炸弹/XML 深度/嵌入对象，任务 2）
 - [x] 上传幂等（workspace+upload_id，任务 11）
 - [x] 解析资源上限（CPU/内存/磁盘，任务 2、10）
 - [x] 临时目录清理（任务 2 cleanup_tempdir）
 - [x] 查重哈希而非明文（任务 9）
 - [x] PII 加密落库且不写 candidate JSON/search_text/vector 文本（encrypt_secret + pii_mappings，任务 9）

**已知边界（后续计划处理）：**
- F5 知识库 / chat 的真实 embedding 与历史 Chunk 重向量化 → P3（A-16；P2 仅完成简历领域真实 embedding）。
- 人才画像第三层 Candidate×Job 动态匹配 → P3（F7 搜人）。
- 查重合并操作（F12）→ P3。
- 人工修正 override API / UI（F8）→ P3（表与合并视图已在任务 1/9 预留）。
- 软删除恢复 API（F8）→ P3。
- rerank（bge-reranker-v2-m3）→ P3（F7 搜人）。
- 中文全文分词（pg_jieba）→ P3。
- 解析评测 bundle（AI Studio 数据集 + manifest + 评分器）→ P3/M3 评测任务。

---

## 执行交接

**计划已完成并保存到 `docs/superpowers/plans/2026-08-07-p2-resume-parsing.md`。两种执行方式：**

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

**选哪种方式？**
