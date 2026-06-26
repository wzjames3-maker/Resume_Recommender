<!-- Module: resume-parser -->
<!-- Spec Layer: 00 - Overview -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 模块概览：Resume Parser（简历解析模块）

## 1. 模块定位

Resume Parser 是企业智能招聘 RAG 推荐系统的**基础数据入口模块**，负责将各种格式的简历文件解析为结构化的 Resume 实体，为下游的 Resume Store（持久化存储）和 Vector Index（向量索引）提供统一的数据源。

## 2. 来源追溯

| 来源 | 内容 |
|------|------|
| PRD FR-010 | 支持简历上传（PDF / DOCX / JSON） |
| PRD FR-011 | 支持 Resume Parser（PyPDF2/pdfplumber + python-docx + DeepSeek-OCR + LLM 结构化提取） |
| PRD FR-012 | 支持语义段落切分（教育/工作/项目/技能），保留 Metadata |
| PRD FR-013 | 支持 Skill 标准化（大小写统一、同义词映射） |
| PRD UC-005 | 简历上传入库 |
| Domain Model | Resume(1:N Education, Experience, Project, Skill) |

## 3. 做什么（In Scope）

| 能力 | 说明 |
|------|------|
| PDF 简历解析 | 支持文本型 PDF（pdfplumber 优先，PyPDF2 降级）和扫描件型 PDF（OCR） |
| DOCX 简历解析 | 支持 .docx 格式简历的文本提取和结构化 |
| 图片简历 OCR | 支持 jpg/png 格式图片简历，使用 DeepSeek-OCR 进行文字识别 |
| JSON 简历导入 | 支持已结构化的 JSON 格式简历直接导入 |
| LLM 结构化提取 | 使用 LLM（DeepSeek）将非结构化文本提取为结构化 Resume 实体 |
| 语义段落切分 | 按教育/工作/项目/技能等语义维度切分为 Section（Parent Chunk），再细分为 Small Chunk（单句级），保留层级关系和 Metadata |
| Skill 标准化 | 大小写统一、同义词映射，维护 Skill 标准化词典 |
| 解析失败降级 | 解析失败时保留原文、标记解析状态，保证不丢数据 |

## 4. 不做什么（Out of Scope）

| 不做 | 说明 | 负责模块 |
|------|------|----------|
| 简历评分 | 不对简历质量打分 | recommendation-engine |
| 简历推荐 | 不做候选人匹配和排序 | recommendation-engine |
| 批量导入队列管理 | V1 不做异步队列，同步处理 | -（V2 可引入 Celery） |
| 简历持久化 | 解析结果交给 resume-store 写入 MongoDB | resume-store |
| 向量索引 | 解析结果交给 vector-index 生成 Embedding | vector-index |
| 简历 CRUD 管理 | 不做简历的删除/更新等管理操作 | resume-store |

## 5. 技术栈

| 组件 | 技术选型 | 版本要求 | 用途 |
|------|----------|----------|------|
| PDF 文本提取 | pdfplumber（主） + PyPDF2（备） | pdfplumber >= 0.11, PyPDF2 >= 3.0 | 从 PDF 提取纯文本 |
| DOCX 文本提取 | python-docx | python-docx >= 1.1 | 从 .docx 提取纯文本和表格 |
| 图片 OCR | DeepSeek-OCR | deepseek-ai/DeepSeek-OCR | 图片简历文字识别 |
| 图片处理 | Pillow | Pillow >= 10.0 | 图片预处理（缩放、格式转换） |
| LLM 结构化提取 | DeepSeek（OpenAI Compatible API） | openai SDK | 文本 → 结构化 Resume 实体 |
| 数据验证 | Pydantic | Pydantic >= 2.0 | Schema 定义与输出约束 |
| Web 框架 | FastAPI（内部接口） | FastAPI >= 0.115 | 内部服务接口 |

## 6. 架构位置

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   HR 上传     │────>│ Resume Parser │────>│ Resume Store  │
│  PDF/DOCX/   │     │  (本模块)     │     │  (MongoDB)    │
│  Image/JSON  │     │              │     └──────────────┘
└──────────────┘     │  ┌─────────┐ │
                     │  │ 文本提取  │ │     ┌──────────────┐
                     │  │ PDF/DOCX │ │────>│ Vector Index  │
                     │  │ /OCR     │ │     │  (Milvus)     │
                     │  └────┬─────┘ │     └──────────────┘
                     │       │       │
                     │  ┌────▼─────┐ │
                     │  │ LLM 结构化│ │
                     │  │ 提取      │ │
                     │  └────┬─────┘ │
                     │       │       │
                     │  ┌────▼─────┐ │
                     │  │ Skill    │ │
                     │  │ 标准化    │ │
                     │  └─────────┘ │
                     └──────────────┘
```

## 7. 数据流

```
输入文件 ──> 格式识别 ──> 文本提取 ──> 语义切分 ──> LLM 结构化提取 ──> Skill 标准化 ──> Resume 实体
                                         │
                                         ├── Section (Parent Chunk)
                                         │     └── Small Chunk (单句级)
                                         └── Full Resume (整份简历)
```

## 8. 关键约束

1. **解析失败不丢数据** — 任何环节失败都保留原文，标记 `status=failed`
2. **PII 加密** — 手机号、邮箱等 PII 字段加密存储（AES-256）
3. **LLM 输出约束** — 所有 LLM 提取结果必须通过 Pydantic Schema 验证
4. **同步处理** — V1 采用同步解析，不做异步队列
5. **内部接口** — 不对外暴露，仅供其他模块通过函数调用使用
6. **容器内执行** — 所有测试和运行在 Docker 容器内

## 9. Spec 文件索引

| 文件 | 内容 | 层级 |
|------|------|------|
| `00-overview.md` | 模块概览（本文件） | 概览 |
| `01-requirements.md` | 功能需求列表 | 需求 |
| `02-data-model.md` | 数据模型与 Schema 定义 | 模型 |
| `03-api-contract.md` | 内部接口契约 | 接口 |
| `04-business-rules.md` | 业务规则 | 规则 |
| `05-edge-cases.md` | 边界情况与异常处理 | 边界 |
| `06-acceptance.md` | 验收标准（Given-When-Then） | 验收 |
| `07-tech-constraints.md` | 技术约束与依赖版本 | 约束 |
| `08-dependencies.md` | 模块依赖关系 | 依赖 |
