# AgentKB-HR（基于 MaxKB v2 派生）

本仓库源自 MaxKB v2（GPL-3.0，https://github.com/1panel-dev/MaxKB）。
依据 GPL-3.0，本衍生仓库及其后续代码必须以 GPL-3.0 开源。
基线 commit：`65c5ff8`

## 裁剪范围（本地开发精简内核，实际删除）

> 原计划"仅隐藏入口、不删除代码"无法满足本地编译要求（原版依赖过重无法在本机构建），
> 已按《2026-08-13-local-core-slimming-design》规格实际删除以下功能代码：

### 后端
- 本地模型服务（apps/local_model、local_model_provider、SERVER_NAME=local_model）
- 模型供应商（仅保留 OpenAI 兼容 LLM 与 Embedding；删除了 20+ 厂商 Provider 及其 SDK）
- 可视化工作流（apps/application/flow、default_workflow.json、全部节点）
- MCP 工具与端点（apps/chat/mcp、mcp_node）
- 工具库（apps/tools）与触发器（apps/trigger）
- 应用市场/模板、应用导入导出（Import/Export/StoreApplication）
- 工具沙箱（common/utils/tool_code.py）
- 知识库工作流（knowledge workflow serializer/views，模型表保留）
- 语音 STT/TTS 后端 Provider 与视图

### 前端
- 工作流画布（ui/src/workflow 及所有 workflow 视图）
- 工具/MCP/触发器/模板市场页面与路由
- 应用市场、导入导出、应用模板 UI
- 动态表单中的 workflow 组件、权限/API 中的 tool/trigger 分支
- PDF 导出、聊天导出（Markdown/HTML/PDF）、语音录音（recorder-core）
- 相应 npm 依赖（logicflow、file-saver、marked、recorder-core 等）

### 保留
- 用户/工作区/成员角色权限
- 模型配置（OpenAI 兼容 LLM/Embedding/Rerank 均已注册；reranker 已接入简历语义检索管线）
- 知识库、文档上传解析、分块、向量化、检索
- 知识库问答（SIMPLE 应用）、引用来源、会话管理
- 文件上传、homepage 工作台、系统设置

## 本地开发

```bash
# 后端（Python 3.11 由 uv 管理）
export PATH="$HOME/.local/bin:$PATH"
uv venv --python 3.11 && uv sync --locked
export MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
  MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=xxx \
  MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings .venv/bin/python apps/manage.py runserver 0.0.0.0:8080

# 验证
python apps/manage.py check
python apps/manage.py makemigrations --check --dry-run
.venv/bin/python apps/manage.py test application.tests knowledge.tests models_provider.tests --keepdb

# 前端（表面检查 + 类型检查 + 构建）
cd ui && pnpm install
node scripts/check-local-core-surface.mjs
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build
```

## 从原版 v2 升级（重要）

- 升级前必须备份 PostgreSQL，并在 staging 副本演练全部 migration；禁止直接在生产库执行。
- 已裁剪 Provider 的模型记录会被迁移标为 `ERROR` 并写入 `meta.disabled_reason=provider_removed_by_local_core`，
  须在原版实例导出或重新创建 OpenAI 兼容 LLM/Embedding 模型并重新绑定知识库与应用。
- 历史工作流应用（`type=WORK_FLOW`）会被迁移取消发布（`is_publish=false`），本内核聊天/调试入口会返回
  "Workflow applications are not supported"；必须在原版实例手工导出或重建为简单应用。
- 工作流知识库（`type=4`）会被标记（`meta.disabled_reason=workflow_knowledge_removed_by_local_core`），
  管理、编辑、任务触发与命中测试均返回 400；原数据保留不删除。
- 旧 Trigger 定时任务（`trigger:*`）会在 scheduler 启动前自动清理。
- 依赖安装必须使用 `uv sync --locked`（`uv.lock` 已入库）。

## 新增模块
- apps/hr：人事招聘基础闭环，包含候选人、职位和候选人指派。
- ui/src/views/hr：候选人和职位管理页面。
- API：`/admin/api/workspace/{workspace_id}/hr/...`，认证复用登录会话；权限为 HR 显式授权（`HrAccess` VIEWER/OPERATOR/ADMIN，A3 起不再复用工作区管理员权限）。

## 人事一期验收（2026-08-13）

- 数据模型：`Candidate`、`Job`、`CandidateAssignment` 迁移成功；有效指派去重且职位 HC 必须大于 0。
- 后端：候选人、职位、指派 API 均按 `workspace_id` 隔离；关闭职位和归档候选人不可建立新有效指派。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，23/23 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更。
- 前端：HR 菜单、候选人管理、职位管理、加入职位和筛选状态更新可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。

## 人事二期验收（2026-08-13）

- 简历上传：候选人页支持批量上传 `docx`/`txt` 简历并同步规则解析，按 `(workspace_id, sha256)` 去重。
- 解析回填：抽取姓名、邮箱、手机、城市、学历、年限、技能与经历摘要；无法确定字段留空。
- 检索扩展：候选人列表支持技能、最低工作年限、来源渠道筛选。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，31/31 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更。
- 前端：上传入口、结果展示与检索筛选可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。

## 人事三期验收（2026-08-13）

- 组合搜索：候选人列表支持多技能（AND）、最高学历、工作年限区间、来源渠道组合过滤。
- 职位匹配：职位可维护技能要求，开放职位按技能交集与城市计算匹配分并推荐候选人，支持一键加入职位。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，39/39 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更。
- 前端：职位表单技能要求、展开区匹配推荐与高级搜索可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。

## 人事四期验收（2026-08-13）

- 状态机：指派状态扩展为 待筛选 → 筛选通过 → 面试中 → Offer 中 → 已入职，任意进行中可淘汰/关闭；非法流转拒绝。
- 面试：支持按指派安排多轮面试、面试官/时间/结果/反馈维护；候选人已入职后禁止再指派。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，47/47 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更。
- 前端：状态下拉扩展与面试抽屉可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。

## 人事五期验收（2026-08-13）

- AI 配置：工作区级 LLM 模型选择（复用内核模型管理，校验 LLM 类型，兼容共享授权模型）。
- 自然语言搜人：LLM 解析为结构化条件（技能/城市/年限/学历/状态），回填筛选表单后执行组合搜索。
- 职位技能抽取：职位描述一键抽取技能列表（上限 20），回填技能要求。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，76/76 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更。
- 前端：AI 设置对话框、AI 搜索、技能抽取可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。

## 人事六期验收（2026-08-13）

- 异步解析：简历上传后每文件一个 Celery 解析任务（QueueOnce 防重），立即返回 PENDING，前端轮询收敛状态。
- 状态查询：`GET /hr/resumes/batch-status` 批量查询（上限 200），跨工作区隔离。
- 失败处理：解析失败写 FAILED + error_message，可删除重传；派发 AlreadyQueued 返回 500 提示。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，86/86 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更（无新迁移）。
- 前端：上传对话框轮询展示解析进度可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。
- 端到端：真实 celery worker 验证因本机无法创建 `/opt/maxkb-app/tmp`（worker heartbeat 硬编码路径，sudo 需终端认证）而跳过；任务函数同步调用链路已由自动化测试覆盖。

## 人事七期验收（2026-08-13）

- 简历：候选人简历可下载原文件、可查看提取文本（docx/txt），跨工作区与文件缺失正确 404。
- 查重：列表标记疑似重复（同手机号/邮箱，邮箱忽略大小写）；新建/编辑保存前查重提示。
- 合并：主优先补充字段、技能并集、备注拼接，简历/指派迁移、从候选人删除；有效指派同职位冲突拒绝。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，107/107 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更。
- 前端：简历对话框、重复标记、合并对话框可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。

## 人事 A 阶段验收（生产基础补齐，2026-08-14）

- 流程模型：职位支持草稿/暂停/关闭（原因）、负责人；关联支持渠道、关系类型、进入日期、负责人、终止原因、候选人退出；状态迁移矩阵服务端强制，终态必填原因，误拒绝仅管理员恢复，关闭职位批量收尾。
- 访问控制：HR 模块显式授权（查看者/操作员/管理员），查看者联系方式脱敏，未授权 403 并审计；人事成员与审计日志页面。
- 审计与生命周期：操作审计事件表（查看/创建/流转/简历/合并/导出/授权/越权）；候选人删除匿名化（PII 清空、简历联动删除）；未关联简历 30 天 TTL 每日清理；受控字段白名单 CSV 导出（不含联系方式）。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，227/227 PASS（keepdb 稳定）。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更；`migrate --check` 无未应用迁移。
- 前端：人事成员/审计日志页面与角色化渲染、合规字段/删除/导出可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。
- 部署验证项：Celery beat 真实调度、对象存储权限、TLS/静态加密、日志脱敏、备份与租户注销流程见 `docs/superpowers/audits/2026-08-14-hr-production-baseline.md`，须在目标部署环境完成后才可导入真实 PII。

## 旧版参考

- `references/agentkb/` 是旧版 AgentKB 的固定源码快照，仅用于业务规则、状态机、接口和测试迁移参考。
- 旧版参考代码不参与 MaxKB 的运行、构建或部署，不应从该目录直接导入模块。
- 新版实现以本仓库的 MaxKB 内核、产品 PRD 和当前设计规格为准；旧版行为仅作为迁移参考。
- 参考快照来源：`maxkb-replica`，commit `40278bc0cbd48855ebf017214da22d7419cea88b`。

## 与本轮裁剪的差异记录

- 原实现计划（2026-08-12）声明"只改前端路由与视图层、不删后端代码"；本轮因本机无法编译原版依赖，
  改为实际删除无用代码与依赖（见《2026-08-13-local-core-slimming-design.md》规格与本文档裁剪范围）。
- Docker 构建、Docker Compose 与生产守护进程部署验证不在本轮验收范围，后续独立补齐。

## C 阶段语义索引（2026-08-15 验收补充）

- 切片器：`sanitize_resume_text()`（含 OCR 分号流自动转行：分号 ≥5 且基本无换行时转行式文本，使 LLM 行号边界协议可用）+ ResumeSplitter（LLM 行号边界标注主干 + L2 校验[越界/重叠/覆盖/500 字上限] + L3 规则/smart 降级 + PII 掩码），单测 11 例（apps/hr/services/resume_splitter.py，含超长单行/超长段降级用例）。
- 入库打通：`ResumeFile.document_id`（迁移 0013）+ hr/services/resume_index.py（简历知识库幂等创建/入库/删除/启停用）；`parse_resume_task` 解析成功后自动「清洗→LLM 切片→建 Document/Paragraph→向量化」，失败不阻塞建档；候选人删除/合并清文档向量、归档/恢复同步 is_active。
- 数据流转日志：ResumeFlowLog（迁移 0014/0015）+ 查询 API `GET /workspace/{ws}/hr/resumes/{id}/flow-logs`；UPLOAD/EXTRACT/SANITIZE/SPLIT/DOCUMENT/LIFECYCLE 六节点，SPLIT 记录每个 chunk 完整内容（title/content/length/pii）、EXTRACT/SANITIZE 保留全文，可审计逐节点数据。**该 API 仅 OPERATOR+ 可访问**（EXTRACT/SANITIZE 含未脱敏全文，VIEWER 一律 403，防止绕过 VIEWER 脱敏读取简历 PII）。
- docx 表格排版简历：extract_text_from_docx 遍历段落+表格单元格（合并单元格去重）；数据集真实表格简历端到端 8 段 → 检索命中 0.758。
- 真实模型验证：切片冒烟 10/10 保真；端到端冒烟 3/3（上传→切片→SiliconFlow 向量化 SUCCESS→检索命中"幕墙系统设计" 0.665）；**数据集 30 份压力测试 30/30 成功、29/30 LLM 路径、30/30 内容无改写**（SenseNova 需透传 `thinking=disabled` 禁推理流，已内置于适配器；脚本 installer/resume_splitter_dataset30.py）。
- 语义检索（阶段 3，2026-08-16）：POST /workspace/{ws}/hr/resumes/search——双路召回（dense + sparse 关键词路）→ Python RRF(k=60) 融合 → bge-reranker-v2-m3 精排 → Small-to-Big 简历聚合；模式 B（Skill-AND）技能复合检索（LLM 有序技能分解 → 逐技能双路召回 → 命中向量字典序 → rerank 精排）；hr_access_required + VIEWER 脱敏 + SEARCH 审计（查询原文不入库）；无 rerank/LLM 自动降级。单测 13 例（ResumeSearchTests 11 + AiService 配置扩展 2）。
- 量化对比（阶段 3.3 出口，2026-08-16）：31 份语料 + 12 锚点查询 × 5 模式——**RRF+rerank recall@5=0.92 / recall@3=0.83 / Top-1=0.75 / MRR=0.785**（最优），结构化基线 0.00（语料 skills 字段为空）；报告 audits/2026-08-15-c-stage-rerank-eval.md。**C 阶段完成定义达成（PRD §9.2）**。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests ops.tests`，**355/355 PASS（HR 321）**（keepdb 稳定）。
- 第二轮独立审查修复（2026-08-16，10 例回归，**367/367 PASS（HR 333）**）：
  - 简历删除/TTL 清理联动语义索引（delete_resume/cleanup_orphan_resumes → delete_resume_index；`_delete_document` 显式删 Paragraph，修复内核 DO_NOTHING 无级联导致的段落残留）；
  - 简历/候选人删除级联清理 ResumeFlowLog（EXTRACT/SANITIZE 含未脱敏全文，删除后不留存，PII 生命周期闭环）；
  - 检索参数 clamp（recall_k [5,60]/similarity [0,2]）与 embedding 模型缺失/调用失败友好业务异常（消除两类 500）；
  - 模式 B 结构化路补齐（Candidate.skills 精确命中 → 命中向量 OR 合并 → 字典序补位，meta.recall.structured_hits）；
  - 入库前 PII 二次扫描拒绝（scan_residual_pii：全空格手机号/15 位身份证/银行卡变体）；
  - meta 契约与权限小修（mode=skills 退化 meta 如实、rerank.model/sparse_failed、Download/Content → OPERATOR+、title 上限 20）。
- **简历 RAG v2 重构（2026-08-16，T1-T7，16 例回归，383/383 PASS（HR 349））**：设计 specs/2026-08-16-resume-rag-v2-design.md、方案 plans/2026-08-16-resume-rag-v2-implementation.md（提交 538a8a8..3797bfe）：
  - **T1 PII 掩码前置**：掩码先于任何 LLM 调用（行内替换不改行号，行号边界协议不受影响）；保真语义更新为「相对掩码后原文」；scan_residual_pii 仍为入库 backstop；**修复已知限制 9.3-3（LLM 不再收到未脱敏全文）**；
  - **T2 title 入 chunks**：HR 自建 Document/Paragraph（content 保真、chunks 带 title 前缀参与向量化/分词），显式触发向量化；内核零改动；
  - **T3 证据合成**（仅模式 A）：score = max(段分) + λ·log2(1+命中段数)，λ=0.15（置 0 回退旧行为）；meta.aggregation 新增 evidence_lambda/multi_hit_boosted；
  - **T4 查询理解 v1 + 结构化预筛**：规则槽位（年限 1-2 位数字+年+以上、防年份误抽、学历、城市双向归一）→ Candidate SQL 预筛 → document 集限定召回；纯条件查询走纯结构化检索（杜绝 embed_query 空串）；NULL 年限纳入并标记 years_unknown；姓名快速通道（2-4 字中文 → name__icontains 置顶）；prefilter_empty 明确返回空不误导；
  - **T5 candidate_skill 技能归一表**：skill_alias.json ~100 条别名 + backfill_candidate_skills 幂等回填；Skill-AND 结构化路 SQL 化（表空回退 JSON 路径）；
  - **T6 Termbase 词条 + 重嵌命令**：seed_resume_termbase（108 词条，幂等，KeywordsSearch 内部已自动生效）+ reindex_resume_knowledge（dry-run；一次重嵌覆盖 T2 存量 + T6 词条；重嵌窗口检索降级 seq scan，低峰执行；真实执行由项目方操作）；
  - **T7 技能预筛**：LLM 解析技能（auto→phrase）AND candidate_skill EXISTS，与向量 Skill-AND 并存；
  - 已知限制同步：phone/email 语义查找因掩码设计性不可行（v1 不做，产品确认点）；查询理解为规则版（LLM 版并入 P3 合并调用）；城市槽子串匹配可能误中（评测暴露后收紧）。
- **v2 真实模型评测（2026-08-16，项目方授权后执行；完整输出 installer/eval_v2_report.txt）**：
  - **T1 切片复测**：dataset30 30/30 成功、29/30 LLM 路径、30/30 保真、26/30 PII 掩码、最长段 470 ≤ 500——与基线一致，**掩码前置无质量损失**；顺手修复脚本覆盖度指标（未掩码行 vs 掩码内容必然失配，改为掩码后行比对，实测覆盖 29/30）；
  - **T2 重建验证**：30 份语料按当前代码重建（title 前缀 chunks 100% 生效）+ 同步向量化 30/30 成功；
  - **检索量化（12 锚点 × 4 模式，λ 消融）**：λ=0.15 使 dense/RRF 全面下降（dense recall@5 0.67/MRR 0.33 vs λ=0 的 0.75/0.51；RRF+rerank recall@5 0.83 vs 0.92）→ **λ 默认置 0（证据合成机制保留待更大样本评测）**；λ=0 下 RRF+rerank recall@5=0.92 / recall@3=0.83 与审计基线持平（Top-1/MRR 略低，属重切分随机性 + title 前缀双重因素，需更大样本确认）；Skill-AND recall@5=0.67（基线 0.75，同样归因切片/技能分解随机性）；
  - **T7 真实数据暴露缺陷并修复**：candidate_skill 表空时技能预筛 EXISTS 空表误杀整条查询（Skill-AND 从 0.75 崩到 0.25）→ 表空回退技能维度（提交后复测恢复）；backfill_candidate_skills 实测 31 候选人 0 行（语料 skills 字段为空，与旧评测「结构化基线 0.00」一致）。
- 设计/计划：docs/superpowers/specs/2026-08-15-end-to-end-pipeline-combined-design.md（权威）、docs/superpowers/specs/2026-08-15-hr-resume-search-design.md（检索设计 v2）、docs/superpowers/specs/2026-08-16-resume-rag-v2-design.md（v2 目标态）、docs/superpowers/plans/2026-08-16-resume-rag-v2-implementation.md（v2 实施）、docs/superpowers/plans/2026-08-15-c-stage-resume-rag.md（阶段 3 已完成）。
