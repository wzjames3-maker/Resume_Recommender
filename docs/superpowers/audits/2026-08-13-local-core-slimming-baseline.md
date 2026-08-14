# 本地开发精简内核裁剪基线

> 依据：`docs/superpowers/specs/2026-08-13-local-core-slimming-design.md`。
> 执行环境：worktree `/home/wzjames/toC/maxkb/.worktrees/slim-local-core`，分支 `slim-local-core`。

## 基线命令与结果（2026-08-13）

| 命令 | 结果 |
|------|------|
| `git status --short` | 仅 `apps/maxkb/const.py`（LOG_DIR 本地化改动） |
| `git log --oneline -5` | `a396a6d` chore: 忽略本地 worktree 目录 起 |
| `.venv/bin/python -m compileall -q apps` | 通过 |
| Django `django.setup()`（ENV 配置） | 通过 |

## Python 运行环境

- `pyproject.toml` 要求 Python `~=3.11.0`。
- 本机系统仅有 python3.12/3.14；已用 `uv python install 3.11` 安装 CPython 3.11.15（Linux）。
- 项目使用 uv 管理依赖；本机 `uv` 原为 Windows shim，已改走 `~/.local/bin/uv`（Linux 原生）。
- `uv sync` 成功生成 `uv.lock`（约 203 KB）。

## 已确认的环境适配（本地开发必需）

- `apps/maxkb/const.py:12`：`LOG_DIR` 原硬编码 `/opt/maxkb/logs`，本机无权限创建；改为
  `os.getenv('MAXKB_LOG_DIR') or os.path.join(PROJECT_DIR, 'logs')`。
- 配置读取：`MAXKB_CONFIG_TYPE=ENV` + `MAXKB_*` 环境变量；或提供 `config.yml`。

## 后端引用快照（删除候选命中）

- 命中 `tools|trigger|local_model|models_provider.impl.*|workflow|mcp` 的 Python 文件：318 个。
- 目录体量（后端）：`apps/models_provider` 5.7 MB、`apps/application` 4.6 MB、`apps/knowledge` 2.0 MB、
  `apps/common` 2.4 MB、`apps/tools` 728 KB、`apps/trigger` 600 KB。

### 关键耦合（来自探索分析）

1. `apps/maxkb/settings/base/web.py`：`INSTALLED_APPS` 含 `tools`、`trigger`。
2. `apps/maxkb/urls/web.py`：包含 `tools.urls`、`trigger.urls`。
3. `apps/oss/serializers/file.py:28`：`UploadedFileField` 来自 `tools.serializers.tool`。
4. `apps/folders/serializers/folder.py`、`apps/system_manage/serializers/user_resource_permission.py`、
   `apps/users/serializers/user.py`：含 Tool 分支。
5. `apps/knowledge/serializers/knowledge_workflow.py`、`apps/knowledge/views/knowledge.py`：引用 application workflow 与工具 API。
6. `apps/application` 是知识库问答的宿主：保留 Application/ApplicationVersion/ApplicationKnowledgeMapping/访问令牌/chat_pipeline，删除 flow/MCP/工具/多媒体。
7. `apps/local_model` 关联 `SERVER_NAME=local_model`、settings/model.py、urls/model.py、wsgi、服务命令与 local_model_provider。
8. `apps/models_provider/constants/model_provider_constants.py` 静态注册多个 Provider；`tools.py` 按名称取 Provider。
9. 初始迁移 `apps/models_provider/migrations/0001_initial.py` 内嵌 `model_local_provider` EMBEDDING 种子行。
10. `apps/common/log/log.py:9` 有未使用的 `from qianfan.utils.utils import get_ip_address`。

### Provider 目录清单（apps/models_provider/impl/）

保留：`openai_model_provider/`（LLM + Embedding；OpenAI Provider 注册 LLM/EMBEDDING/STT/TTS/IMAGE/TTI，需裁剪到 LLM/EMBEDDING）。

删除候选（共 22 个）：`aliyun_bai_lian`、`anthropic`、`aws_bedrock`、`azure`、`deepseek`、`docker_ai`、`gemini`、`kimi`、`local_model`、`minimax`、`ollama`、`qwen`、`regolo`、`siliconCloud`、`tencent_cloud`、`tencent`、`vllm`、`volcanic_engine`、`wenxin`、`xf`、`xinference`、`zhipu`。

Rerank 决定：本轮不支持 Rerank；删除全部 Rerank Provider 实现，OpenAI Provider 只保留 LLM/EMBEDDING。

## 前端引用快照（删除候选命中）

- 命中 `tools|trigger|local_model|workflow|mcp|TemplateStore|LogicFlow|recorder-core` 的 TS/Vue 文件：387 个。

### 关键耦合（来自探索分析）

1. `ui/src/router/routes.ts:4`：`import.meta.glob('./modules/*.ts', { eager: true })` 全量加载路由模块。
2. `ui/src/components/index.ts`、`ui/src/components/dynamics-form/index.ts`：全量注册组件（含 workflow/工具）。
3. `ui/src/utils/dynamics-api/shared-api.ts`：静态导入 tools/apps/workflow/trigger/资源 API。
4. `ui/src/views/knowledge/component/KnowledgeListContainer.vue:443`：静态 import 工作流创建、模板市场、共享资源等。
5. `ui/src/views/document/index.vue:937`：静态 import 工作流执行记录。
6. `ui/src/views/chat/index.vue:18`：`import.meta.glob('@/views/chat/**/index.vue')` 全量加载聊天变体。
7. `ui/src/components/ai-chat/component/answer-content/index.vue`：引用 workflow 图标。
8. `ui/src/views/model/component/Provider.vue`、`ModelCard.vue`：本地模型 Provider 分类与下载控制。
9. `ui/src/components/dynamics-form/items/model/provider-data.ts`：静态 Provider 列表含已删 Provider。

### 前端 npm 依赖删除候选

直接候选：`@antv/layout`、`@logicflow/core`、`@logicflow/extension`、`cron-validator`、`html-to-image`、`html2canvas`、`jspdf`、`svg2pdf.js`、`echarts`、`recorder-core`、`vue3-menus`。

删除引用后确认：`@codemirror/*`、`vue-codemirror`、`vue-draggable-plus`、`dingtalk-jsapi`、`file-saver`、`mermaid`、`screenfull`、`katex`、`highlight.js`、`cropperjs`、`@he-tree/vue`、`md-editor-v3`。

## 验证命令集

```bash
# 后端静态
python -m compileall -q apps
python apps/manage.py check
python apps/manage.py makemigrations --check --dry-run
python apps/manage.py showmigrations --plan

# 前端
cd ui
pnpm exec vue-tsc --build
pnpm exec vite build
pnpm exec vite build --mode chat
pnpm exec eslint .
```

---

## 审查修复阶段验收记录（2026-08-13 补充）

执行环境：`.worktrees/slim-local-core`（`slim-local-core` 分支），docker `pgvector/pgvector:pg16`（127.0.0.1:5432）。

### 验收命令与结果

| 命令 | 结果 |
|------|------|
| `compileall -q apps main.py` | PASS |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `manage.py test application.tests knowledge.tests models_provider.tests --keepdb` | 12/12 PASS |
| `ui: node scripts/check-local-core-surface.mjs` | PASS |
| `ui: vue-tsc --build` | PASS |
| `ui: vite build` / `vite build --mode chat` | PASS；产物无 `/workflow|/mcp_tools|/text_to_speech|/speech_to_text|/play_demo_text` |
| Provider 注册表 | 仅 `model_openai_provider` |

### v2 → 精简内核升级演练（隔离库 maxkb_v2，PostgreSQL 16 + pgvector）

准备：从已迁移 schema 克隆库 → 回滚 `application.0015` / `knowledge.0012` / `models_provider.0002`（noop 反向）→
按 v2 状态注入数据（`model_local_provider`/`model_deepseek_provider` 模型、已发布 `WORK_FLOW` 应用与版本、
`type=4` 工作流知识库、`trigger:fake-1` 与 `clean_chat_log` APScheduler job）→ 重放迁移。

| 验证项 | 结果 |
|--------|------|
| `model` 表旧 Provider | 均为 `ERROR`，`meta.disabled_reason=provider_removed_by_local_core` |
| `application` 表 `type=WORK_FLOW` | `is_publish=false`；聊天/调试入口抛 `ChatException`（not supported） |
| `knowledge` 表 `type=4` | `meta.disabled_reason=workflow_knowledge_removed_by_local_core`；Operate/HitTest 抛 400 |
| `django_apscheduler_djangojob` | `trigger:*` 在 scheduler import 时被清理；`clean_chat_log` 保留 |
| `get_provider('model_local_provider')` | `AppApiException`，消息含 provider 名，无裸 `KeyError` |

---

## 人事一期验收记录（2026-08-13）

实现范围：新增 `apps/hr` 的候选人、职位和候选人指派模型、工作区隔离 API，以及 Vue 管理端的“人事部”候选人与职位页面。
本期未引入工作流、MCP、工具、简历解析、RAG、LLM 调用或任何已裁剪 Provider。

| 验证项 | 结果 |
|--------|------|
| `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb` | 23/23 PASS |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `ui: node scripts/check-local-core-surface.mjs` | PASS |
| `ui: vue-tsc --build` | PASS |
| `ui: vite build` / `vite build --mode chat` | PASS；产物无已裁剪端点 |
| HR 约束测试 | 有效指派唯一、终态可重新指派、HC 大于 0、关闭职位/归档候选人约束、跨工作区资源读写 404、管理员写权限均覆盖 |

---

## 人事二期验收记录（2026-08-13）

实现范围：`ResumeFile` 模型与 `(workspace_id, sha256)` 去重约束、docx/txt 规则解析、上传/列表/删除 API、候选人检索扩展与候选人页上传 UI。
本期未引入 LLM 画像、PII 加密、PDF/CSV 简历或异步 worker。

| 验证项 | 结果 |
|--------|------|
| `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb` | 31/31 PASS |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `ui: node scripts/check-local-core-surface.mjs` | PASS |
| `ui: vue-tsc --build` | PASS |
| `ui: vite build` / `vite build --mode chat` | PASS；产物无已裁剪端点 |
| 简历功能测试 | 解析回填、同工作区去重、跨工作区独立、格式/大小拒绝、解析失败保留错误原因均覆盖 |

---

## 人事三期验收记录（2026-08-13）

实现范围：`Job.skill_requirements` 技能要求、候选人高级组合搜索（多技能 AND、学历、年限区间、来源）、职位匹配建议 API 与前端展示、一键加入职位。
本期未引入 LLM 意图解析、画像或检索索引。

| 验证项 | 结果 |
|--------|------|
| `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb` | 39/39 PASS |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `ui: node scripts/check-local-core-surface.mjs` | PASS |
| `ui: vue-tsc --build` | PASS |
| `ui: vite build` / `vite build --mode chat` | PASS；产物无已裁剪端点 |
| 搜索与匹配测试 | 多技能 AND、学历/年限区间/来源过滤、技能与城市加分、分数降序、无要求返回空、关闭职位拒绝、跨工作区 404 均覆盖 |

---

## 人事四期验收记录（2026-08-13）

实现范围：指派状态机扩展（INTERVIEWING/OFFER/HIRED）、合法流转校验、Interview 面试记录模型与 API、候选人已入职禁止再指派、前端面试抽屉。
本期未引入面试官权限差异、Offer 附件、审计事件表或自动提醒。

| 验证项 | 结果 |
|--------|------|
| `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb` | 47/47 PASS |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `ui: node scripts/check-local-core-surface.mjs` | PASS |
| `ui: vue-tsc --build` | PASS |
| `ui: vite build` / `vite build --mode chat` | PASS；产物无已裁剪端点 |
| 状态机与面试测试 | 完整流转链、非法流转拒绝、终态不可再流转、HIRED 禁止再指派、关闭职位限制、面试轮次自增、跨工作区 404 均覆盖 |

---

## 人事五期验收记录（2026-08-13）

实现范围：HrConfig 工作区级 LLM 配置、自然语言搜索条件解析、职位描述技能抽取、前端 AI 设置对话框与两处功能入口。
本期未引入 Embedding 语义检索（后续期候选）、异步任务（六期）、简历下载与候选人合并（七期）。

| 验证项 | 结果 |
|--------|------|
| `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb` | 76/76 PASS |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `ui: vue-tsc --build` | PASS |
| `ui: vite build` / `vite build --mode chat` | PASS；产物无已裁剪端点 |
| 服务层 | LLM 契约（invoke/content）、JSON 容错、年限倒挂交换、技能清洗去重截断、配置校验（LLM 类型/共享模型/未配置 400）、实例化路径 LLM 类型校验均覆盖 |

---

## 人事六期验收记录（2026-08-13）

实现范围：简历解析 Celery 异步化（每文件一任务 + QueueOnce）、上传接口异步派发、批量状态查询接口、前端上传轮询。
本期未引入任务自动重试、上传历史页、简历下载与候选人合并（七期）。

| 验证项 | 结果 |
|--------|------|
| `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb` | 86/86 PASS |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected（无新迁移） |
| `ui: vue-tsc --build` | PASS |
| `ui: vite build` / `vite build --mode chat` | PASS；产物无已裁剪端点 |
| 任务函数 | 成功建候选人+SUCCESS、损坏文件 FAILED+error_message、缺失简历静默、事务原子性均覆盖 |
| 上传/查询 | PENDING+派发、duplicate 同步判定、AlreadyQueued 500、派发异常降级 FAILED、ids 上限 200、跨工作区隔离、路由顺序修正、路由冒烟均覆盖 |
| 端到端（真实 worker） | 跳过：worker heartbeat 硬编码 `/opt/maxkb-app/tmp`，本机无该目录且 sudo 需终端认证；任务函数同步链路已由测试覆盖 |
