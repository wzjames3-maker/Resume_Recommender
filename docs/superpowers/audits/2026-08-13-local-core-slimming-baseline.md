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
