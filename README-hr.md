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
- 模型配置（仅 OpenAI 兼容 LLM/Embedding、Rerank 暂不支持）
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
- API：`/admin/api/workspace/{workspace_id}/hr/...`，复用当前工作区认证与管理员权限。

## 人事一期验收（2026-08-13）

- 数据模型：`Candidate`、`Job`、`CandidateAssignment` 迁移成功；有效指派去重且职位 HC 必须大于 0。
- 后端：候选人、职位、指派 API 均按 `workspace_id` 隔离；关闭职位和归档候选人不可建立新有效指派。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，23/23 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更。
- 前端：HR 菜单、候选人管理、职位管理、加入职位和筛选状态更新可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。

## 旧版参考

- `references/agentkb/` 是旧版 AgentKB 的固定源码快照，仅用于业务规则、状态机、接口和测试迁移参考。
- 旧版参考代码不参与 MaxKB 的运行、构建或部署，不应从该目录直接导入模块。
- 新版实现以本仓库的 MaxKB 内核、产品 PRD 和当前设计规格为准；旧版行为仅作为迁移参考。
- 参考快照来源：`maxkb-replica`，commit `40278bc0cbd48855ebf017214da22d7419cea88b`。

## 与本轮裁剪的差异记录

- 原实现计划（2026-08-12）声明"只改前端路由与视图层、不删后端代码"；本轮因本机无法编译原版依赖，
  改为实际删除无用代码与依赖（见《2026-08-13-local-core-slimming-design.md》规格与本文档裁剪范围）。
- Docker 构建、Docker Compose 与生产守护进程部署验证不在本轮验收范围，后续独立补齐。
