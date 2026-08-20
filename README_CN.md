# MaxKB 人事招聘工作台 ATS

本仓库是 **MaxKB v2 精简内核 fork**：保留企业知识库 RAG 底座，并在 `apps/hr` 内嵌多租户人事招聘工作台（ATS）。

产品方向：

```text
MaxKB RAG 内核 + 传统 ATS 流程 + “提议-确认-执行”的 Agent
```

## 仓库状态

- RAG：**已交付**（pgvector + tsvector、RRF、rerank、Small-to-Big）。
- ATS：当前代码以 `Application + JobStage + StageHistory` 为主链；旧固定状态机仅作迁移基线。
- Agent：D1 Screening、D2 JD/Interview Copilot、D3 Sourcing/沟通草稿及 D4 Agent 工作台首版已实现；Screening 默认关闭，按 workspace 灰度启用；后续补跨页指标、原文定位和反馈重试表单。

## 权威文档

| 文档 | 用途 |
|---|---|
| `docs/PRD.md` | 产品基线 |
| `docs/ATS-STATE-MACHINE-V2.md` | 新 ATS 目标设计 |
| `docs/ATS-OPENSOURCE-REFERENCE.md` | 传统 ATS 开源调研 |
| `docs/ATS-DESIGN-SPEC.md` | 当前代码事实，仅迁移对照 |
| `docs/PRD-AGENT-RAG.md` | Agent + RAG 设计 |
| `docs/RAG-V2-DESIGN.md` | 已交付简历 RAG 设计 |
| `docs/RESUME-DATABASES.md` | 总库、多业务库和库内页面设计 |

## 快速开始

见 `README-hr.md` 和 `CLAUDE.md`。

## License

GPL-3.0，继承自 MaxKB；本 fork 及其后续代码必须以 GPL-3.0 开源。
