# 本地开发精简内核实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 删除 MaxKB v2 fork 中无法被本地开发内核使用的代码和依赖，保留可本地检查和编译的用户、工作区、OpenAI 兼容 LLM/Embedding、知识库问答与人事扩展基础。

**架构：** 后端保留 Django、用户/工作区、知识库、文件存储、Celery 和最小的应用问答执行路径；删除本地模型、专用 Provider、MCP、工具和可视化工作流。前端保留登录、工作区、模型配置、知识库、文档和文字问答引用链路，删除对应的编排、市场、媒体和导出功能。

**技术栈：** Python 3.11、Django 5.2、Celery、PostgreSQL/pgvector、Redis、Vue 3、Vite、TypeScript、OpenAI 兼容 API。

---

## 文件职责总表

### 后端保留或收缩

- `apps/maxkb/settings/`：仅加载本地开发所需 Django app、数据库、缓存和静态配置。
- `apps/maxkb/urls/`：保留 Web、管理 API、知识库与问答所需 URL，移除工具、触发器和本地模型 URL。
- `apps/users/`、`apps/system_manage/`：用户、工作区、成员和资源权限；删除 Tool/Trigger 资源分支。
- `apps/common/`：保留认证、字段、文件、向量、响应和模型调用公共代码；删除无用厂商导入。
- `apps/knowledge/`：保留知识库、文档、段落、分块、Embedding 任务与检索；删除知识库工作流路径。
- `apps/oss/`：保留文件存取；将上传字段依赖改到公共模块后解除 `tools` 引用。
- `apps/folders/`：保留知识库和应用文件夹能力；删除 Tool 文件夹分支。
- `apps/application/`：保留简单应用、知识库映射、访问令牌和旧 RAG Chat Pipeline；删除 flow、MCP、工具和多媒体路径。
- `apps/chat/`：保留文字问答、会话和引用响应；删除工具调用、工作流执行和非文字响应路径。
- `apps/models_provider/`：只保留 OpenAI 兼容 LLM 与 Embedding 的配置、凭据、模型和注册入口。
- `apps/ops/`：保留知识库异步任务所需 Celery 启动和任务发现；移除仅服务于触发器/调度器的代码后再决定依赖。

### 后端删除

- `apps/local_model/` 及本地模型设置、URL、服务命令和 Provider。
- `apps/trigger/`。
- `apps/tools/`，在清理所有引用、权限和迁移依赖后删除。
- `apps/application/flow/`、独立工作流序列化器、工具任务和 MCP 适配器。
- `apps/models_provider/impl/` 下除 `openai_model_provider/` 外的 Provider 目录。
- OpenAI Provider 的 STT、TTS、IMAGE、TTI 文件和注册项。
- 仅服务于被删除功能的 `homepage`、调度、媒体、沙箱和配置模块；每项必须先通过引用扫描确认。

### 前端保留或收缩

- `ui/src/router/`：保留登录、用户/工作区、模型、知识库、文档、段落和文字问答路由。
- `ui/src/views/login/`、用户/工作区管理、模型配置、知识库、文档、段落和 `chat/`：保留核心页面。
- `ui/src/components/ai-chat/` 和 Markdown/知识来源组件：保留文字回答与引用展示，移除语音、工具调用和执行进度依赖。
- `ui/src/components/dynamics-form/`：改为仅注册 OpenAI LLM/Embedding 表单实际需要的组件。
- `ui/src/utils/dynamics-api/shared-api.ts`：拆出或收缩为核心知识库、模型、文档 API，避免静态引用已删除功能。
- `ui/src/workflow/`、workflow 视图、工具/MCP 视图、模板市场、触发器和发布视图：删除。

### 前端依赖删除或确认

- 直接删除候选：`@antv/layout`、`@logicflow/core`、`@logicflow/extension`、`cron-validator`、`html-to-image`、`html2canvas`、`jspdf`、`svg2pdf.js`、`echarts`、`recorder-core`、`vue3-menus`。
- 在删除引用后确认：`@codemirror/*`、`vue-codemirror`、`vue-draggable-plus`、`dingtalk-jsapi`、`file-saver`、`mermaid`、`screenfull`、`katex`、`highlight.js`、`cropperjs`、`@he-tree/vue`、`md-editor-v3`。
- 最后根据实际导入图修改 `ui/package.json` 和锁文件，不凭目录大小直接删除依赖。

## 任务 1：建立裁剪前基线和依赖清单

**文件：**
- 读取：`pyproject.toml`、`ui/package.json`、`apps/maxkb/settings/base/web.py`、`apps/maxkb/urls/web.py`、`apps/maxkb/urls/__init__.py`、`ui/src/router/routes.ts`
- 创建：`docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md`

- [ ] **步骤 1：记录当前工作树和基线命令**

运行：

```bash
git status --short
git log --oneline -5
python -m compileall -q apps
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings python -c "import django; django.setup(); print('django setup ok')"
```

记录每条命令的退出状态。当前已有的前端未提交改动不得在本计划中丢弃或覆盖。

- [ ] **步骤 2：建立后端和前端引用快照**

运行：

```bash
rg -n --glob '*.py' --glob '*.ts' --glob '*.vue' --glob '*.json' \
  'tools|trigger|local_model|models_provider\.impl\.|workflow|mcp|TemplateStore|LogicFlow|recorder-core' apps ui/src ui/package.json
```

将输出按“保留链路引用”“删除候选引用”“需要重构的静态注册”三类写入基线文档，并列出受影响的 URL、Django app、Celery 任务和 npm 包。

- [ ] **步骤 3：提交基线文档**

```bash
git add docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md
git commit -m "docs(裁剪): 记录本地精简内核基线"
```

## 任务 2：移除本地模型运行时

**文件：**
- 修改：`main.py`、`apps/maxkb/settings/base/__init__.py`、`apps/maxkb/settings/base/model.py`、`apps/maxkb/urls/__init__.py`、`apps/maxkb/urls/model.py`、`apps/maxkb/wsgi/__init__.py`
- 修改：`apps/common/management/commands/services/command.py`、`apps/common/management/commands/services/services/local_model.py`
- 修改：`apps/models_provider/migrations/0001_initial.py` 或新增兼容迁移（以数据库发布状态为准）
- 删除：`apps/local_model/`、`apps/models_provider/impl/local_model_provider/`

- [ ] **步骤 1：删除本地模型启动入口**

从 `main.py` 删除 `local_model` 服务选择、`SERVER_NAME=local_model` 设置和本地模型绑定逻辑；从 settings、URL、WSGI 和服务管理中删除仅服务于 `local_model` 的分支。保留 `web` 与本地开发所需的 Celery 命令。

- [ ] **步骤 2：处理初始数据和已有模型记录**

检查：

```bash
rg -n 'model_local_provider|LOCAL_MODEL|local_model' apps
python apps/manage.py showmigrations models_provider
```

如果初始迁移尚未发布，直接删除本地模型种子；如果已发布，新增数据迁移删除无法使用的本地模型记录，并在迁移中保留 OpenAI 模型记录。不得直接改写已应用迁移。

- [ ] **步骤 3：删除本地模型代码并清理引用**

删除 `apps/local_model/` 和 `apps/models_provider/impl/local_model_provider/`，再运行：

```bash
rg -n --glob '*.py' 'local_model|model_local_provider|LOCAL_MODEL' apps main.py
python -m compileall -q apps
```

预期：无生产代码引用，编译命令退出码为 0。

- [ ] **步骤 4：提交本地模型裁剪**

```bash
git add main.py apps
git commit -m "refactor(本地模型): 删除本地推理运行时与模型 Provider"
```

## 任务 3：收缩模型 Provider 到 OpenAI LLM/Embedding

**文件：**
- 修改：`apps/models_provider/constants/model_provider_constants.py`
- 修改：`apps/models_provider/impl/openai_model_provider/openai_model_provider.py`
- 修改：`apps/common/log/log.py`
- 修改：`pyproject.toml`
- 删除：`apps/models_provider/impl/` 下除 `openai_model_provider/` 外的目录
- 删除：OpenAI Provider 的 STT、TTS、IMAGE、TTI credential/model 文件及对应 base 文件

- [ ] **步骤 1：固定 Provider 注册表**

将 `ModelProvideConstants` 缩减为一个 `model_openai_provider` 成员；将 OpenAI Provider 的能力缩减为 `LLM` 和 `EMBEDDING`。同时删除未使用的 `qianfan` 导入，避免核心日志模块依赖已删除 SDK。

- [ ] **步骤 2：清理模型类型和未使用导入**

运行：

```bash
rg -n --glob '*.py' 'ModelTypeConst\.(STT|TTS|IMAGE|TTI|ITV|TTV)|base_(stt|tts|tti)|\.model\.(stt|tts|image|tti)' apps
```

删除只服务于非 LLM/Embedding 能力的导入、模型、凭据和注册项。保留 `base_chat_open_ai.py`、LLM 和 Embedding 实现。

- [ ] **步骤 3：删除非 OpenAI Provider 目录**

确认注册表不再导入这些目录后，删除 `apps/models_provider/impl/` 下全部非 OpenAI Provider。随后运行：

```bash
rg -n --pcre2 --glob '*.py' 'models_provider\.impl\.(?!openai_model_provider)' apps
python -m compileall -q apps
```

预期：无非 OpenAI Provider 引用，编译通过。

- [ ] **步骤 4：裁剪 Python 依赖**

从 `pyproject.toml` 删除经引用扫描确认不再使用的厂商 SDK、本地模型、深度学习和 Rerank 依赖；不得删除知识库、OpenAI、Django、Celery、Redis 和 PostgreSQL 依赖。运行 `uv lock` 或当前项目等价的锁文件生成命令，随后执行：

```bash
uv sync
python apps/manage.py check
```

预期：依赖安装不拉取已删除供应商 SDK，Django check 通过。

- [ ] **步骤 5：提交 Provider 裁剪**

```bash
git add pyproject.toml uv.lock apps/models_provider apps/common/log/log.py
git commit -m "refactor(模型): 仅保留 OpenAI 兼容 LLM 与 Embedding"
```

## 任务 4：解除后端工具、触发器和工作流耦合

**文件：**
- 修改：`apps/maxkb/settings/base/web.py`、`apps/maxkb/urls/web.py`
- 修改：`apps/oss/serializers/file.py`、`apps/folders/serializers/folder.py`、`apps/system_manage/serializers/user_resource_permission.py`、`apps/users/serializers/user.py`
- 修改：`apps/knowledge/serializers/common.py`、`apps/knowledge/serializers/knowledge_workflow.py`、`apps/knowledge/views/knowledge.py`
- 修改：`apps/application/serializers/application.py`、`apps/application/chat_pipeline/step/chat_step/impl/base_chat_step.py`、`apps/application/flow/tools.py`
- 修改：`apps/ops/celery/` 中触发器和调度专用代码
- 删除：`apps/trigger/`、`apps/tools/`、独立工作流/MCP 代码和仅被它们使用的迁移/任务

- [ ] **步骤 1：收缩注册入口**

从 `INSTALLED_APPS` 和根 URL 删除 `trigger`、`tools`；删除后运行：

```bash
python apps/manage.py check
python apps/manage.py showmigrations --plan
```

预期：Django 不再因 `tools` 或 `trigger` 的 app config、URL 或 serializer 导入失败。

- [ ] **步骤 2：替换 OSS 上传字段依赖**

将 `apps/oss/serializers/file.py` 中从 `tools.serializers.tool.UploadedFileField` 的导入替换为公共上传字段实现，并增加最小序列化测试，验证文件名、大小和内容类型校验仍保持。

运行：

```bash
python -m compileall -q apps/oss apps/common
```

- [ ] **步骤 3：移除权限、文件夹和导出中的 Tool 分支**

删除 folders、resource permission、workspace export 中的 Tool/Trigger 分支，同时保留 Knowledge、Application、Model 的资源映射。运行：

```bash
rg -n --glob '*.py' '\bTool\b|ToolFolder|Trigger|trigger|tools' apps/folders apps/system_manage apps/users apps/knowledge apps/oss
```

预期：不再存在生产代码对已删除 app 的导入。

- [ ] **步骤 4：将 application 收缩到简单问答路径**

保留 Application、ApplicationVersion、ApplicationKnowledgeMapping、访问令牌和 `chat_pipeline` 中的知识检索/回答步骤；删除 flow、工具调用、MCP、沙箱、循环、媒体和可视化工作流 API。知识库问答不得依赖 `tools`、`trigger` 或 `local_model`。

运行：

```bash
rg -n --glob '*.py' '\b(tools|trigger|mcp|workflow|sandbox)\b' apps/application apps/knowledge apps/chat
python -m compileall -q apps/application apps/knowledge apps/chat
```

- [ ] **步骤 5：处理迁移图**

不要删除已应用迁移中的历史文件。为新的安装状态或已存在数据库新增明确迁移，使 `system_manage` 不再需要加载 `tools` 的迁移依赖，并验证：

```bash
python apps/manage.py makemigrations --check --dry-run
python apps/manage.py showmigrations --plan
```

- [ ] **步骤 6：删除目录并提交后端编排裁剪**

删除 `apps/trigger/`、`apps/tools/` 和已确认不再被简单问答路径引用的工作流代码，运行：

```bash
rg -n --pcre2 --glob '*.py' '\b(tools|trigger|local_model)\b|models_provider\.impl\.(?!openai_model_provider)' apps
python -m compileall -q apps
python apps/manage.py check
```

```bash
git add apps
git commit -m "refactor(后端): 删除工具触发器与可视化工作流耦合"
```

## 任务 5：保证知识库异步任务可发现

**文件：**
- 修改：`apps/ops/celery/__init__.py`、相关任务配置
- 修改：`apps/knowledge/task/embedding.py`、`apps/knowledge/task/generate.py`、`apps/knowledge/task/sync.py` 的发现入口
- 删除：仅服务于触发器、长时记忆或已删工作流的调度任务和依赖

- [ ] **步骤 1：建立知识库任务的显式导入桥**

保证 `knowledge.task.embedding`、`knowledge.task.generate`、`knowledge.task.sync` 被 Celery worker 明确注册，不依赖不存在的 `knowledge.tasks` 自动发现路径。保留文档上传调用的 `.delay()` 目标。

- [ ] **步骤 2：验证任务注册和本地静态检查**

运行：

```bash
python -m compileall -q apps/knowledge apps/ops
python apps/manage.py check
```

有可用 Redis 时再运行：

```bash
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  celery -A ops inspect registered | rg 'embedding_by_document|embedding_by_paragraph|tokenize_by_document'
```

- [ ] **步骤 3：提交任务裁剪**

```bash
git add apps/ops apps/knowledge
git commit -m "fix(任务): 显式注册知识库异步任务"
```

## 任务 6：收缩前端路由和静态注册

**文件：**
- 修改：`ui/src/router/routes.ts`、`ui/src/router/modules/system.ts`、`ui/src/router/modules/document.ts`
- 删除：`ui/src/router/modules/tool.ts`、`ui/src/router/modules/trigger.ts`、工作流/工具/市场/发布相关路由模块
- 修改：`ui/src/components/index.ts`、`ui/src/components/dynamics-form/index.ts`、`ui/src/utils/dynamics-api/shared-api.ts`
- 删除：`ui/src/workflow/`、工作流视图、工具视图、触发器视图、模板市场视图和对应 API/权限目录

- [ ] **步骤 1：只保留核心路由**

保留登录、用户/工作区、模型、知识库、文档、段落和文字问答路由；删除 `tool.ts`、`trigger.ts` 及 workflow/template/publish 路由。由于 `routes.ts` 使用 eager glob，删除整个路由模块并清理它引用的视图，不只给菜单加 `hidden`。

- [ ] **步骤 2：收缩全局组件和动态表单注册**

将全局组件注册与动态表单注册改为显式核心清单，至少保留知识库文档、Markdown、模型配置实际使用的组件；删除 workflow、tool、MCP、媒体和资源市场组件的注册。

- [ ] **步骤 3：收缩动态 API 映射**

从 `shared-api.ts` 删除工具、工作流、触发器、市场、共享资源等映射，保留用户、工作区、模型、知识库、文档和聊天 API。运行：

```bash
rg -n 'tool|workflow|trigger|template|publish|mcp' ui/src/utils/dynamics-api ui/src/api
```

保留页面不得再静态导入已删除 API 文件。

- [ ] **步骤 4：删除前端编排代码并提交**

运行：

```bash
cd ui
pnpm exec vue-tsc --build
pnpm exec vite build
pnpm exec vite build --mode chat
```

```bash
git add ui/src
git commit -m "refactor(前端): 删除工作流工具与市场页面"
```

## 任务 7：删除非核心媒体和导出能力并清理依赖

**文件：**
- 修改：`ui/src/components/ai-chat/`、`ui/src/components/markdown/`、`ui/src/views/chat/`
- 删除：`ui/src/components/pdf-export/`、`ui/src/components/app-charts/`、录音/TTS/媒体组件和仅用于分享导出的代码
- 修改：`ui/package.json`、`ui/pnpm-lock.yaml`、`ui/pnpm-workspace.yaml`

- [ ] **步骤 1：保留文字回答与引用**

保留 Markdown 渲染、知识来源组件和 PDF 引用预览所需的 `pdfjs-dist`；删除工具调用进度、语音输入输出、图表、分享和导出路径。文字问答组件必须仍能渲染回答正文和知识来源。

- [ ] **步骤 2：根据导入图删除 npm 依赖**

运行：

```bash
cd ui
rg -n "from ['\"](@logicflow|@antv/layout|cron-validator|html-to-image|html2canvas|jspdf|svg2pdf.js|echarts|recorder-core|vue3-menus|dingtalk-jsapi|vue-codemirror|vue-draggable-plus|mermaid|screenfull|katex|highlight.js|cropperjs)['\"]" src
```

只删除没有输出的包，并使用项目现有包管理方式重新生成锁文件。不得手工删除锁文件中的单个无关段落。

- [ ] **步骤 3：验证前端精简构建**

```bash
pnpm install --lockfile-only
pnpm exec vue-tsc --build
pnpm exec vite build
pnpm exec vite build --mode chat
pnpm exec eslint .
```

不要运行 `npm run lint`，因为它带 `--fix` 会修改未请求的文件。

- [ ] **步骤 4：提交前端非核心能力裁剪**

```bash
git add ui/package.json ui/pnpm-lock.yaml ui/pnpm-workspace.yaml ui/src
git commit -m "chore(前端依赖): 删除非核心媒体与导出依赖"
```

## 任务 8：最终本地验收和开发说明

**文件：**
- 修改：`README-hr.md`、`docs/superpowers/deviation-log.md`

- [ ] **步骤 1：运行后端最终验收**

```bash
python -m compileall -q apps
python apps/manage.py check
python apps/manage.py makemigrations --check --dry-run
python apps/manage.py showmigrations --plan
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  python -c "import django; django.setup(); from models_provider.constants.model_provider_constants import ModelProvideConstants; assert list(ModelProvideConstants.__members__) == ['model_openai_provider']; print('provider registry ok')"
```

运行：

```bash
rg -n --pcre2 --glob '*.py' --glob '*.ts' --glob '*.vue' \
  'tools|trigger|local_model|models_provider\.impl\.(?!openai_model_provider)|workflow|mcp' apps ui/src
```

预期：只剩明确保留路径或历史迁移中的文字，不存在可执行代码对已删除模块的引用。

- [ ] **步骤 2：运行前端最终验收**

```bash
cd ui
pnpm exec vue-tsc --build
pnpm exec vite build
pnpm exec vite build --mode chat
```

- [ ] **步骤 3：更新开发说明并提交**

在 `README-hr.md` 增加本地裁剪范围、当前只支持 OpenAI 兼容 LLM/Embedding、Rerank 暂不支持和 Docker 未纳入本轮验收。同步在偏差台账记录原计划“仅隐藏入口”已被本地编译约束取代。

```bash
git add README-hr.md docs/superpowers/deviation-log.md
git commit -m "docs(裁剪): 记录本地内核验收范围"
```

---

## 审查修复阶段

**背景：** 任务 1-8 的裁剪提交已完成，但对 `v2...slim-local-core` 的对照审查发现：全新安装可以加载和构建，已有 v2 数据库升级及少数保留页面仍存在运行时断链。本阶段不恢复工作流、工具、MCP、Trigger、语音或专用 Provider；它们的历史数据必须被显式停用或拒绝，不能被静默当作简单应用执行。

**完成标准：**

- `stream=false` 的文字聊天不再引用已删除的 MCP/工具方法。
- 已裁剪 Provider、工作流应用、工作流知识库、Trigger 定时任务在升级后均不会出现裸 `KeyError`、`AttributeError`、模块导入失败或静默降级。
- 前端不再提供会调用已删除后端能力的入口。
- OpenAPI、模型枚举、应用创建请求与精简内核实际支持范围一致。
- 依赖锁文件可复现，且新库安装、升级演练、Django 检查和两套前端构建均通过。

### 任务 9：修复简单问答运行时的工具残留

**文件：**

- 修改：`apps/application/chat_pipeline/step/chat_step/impl/base_chat_step.py:573-639`
- 修改：`apps/application/tests.py`

- [ ] **步骤 1：编写非流式简单聊天的失败回归测试**

在 `apps/application/tests.py` 中用 `SimpleTestCase` 添加最小假模型，覆盖没有命中知识库直返答案、`stream=False` 的 `get_block_result()` 分支：

```python
from django.test import SimpleTestCase
from langchain_core.messages import AIMessage

from application.chat_pipeline.step.chat_step.impl.base_chat_step import BaseChatStep


class FakeChatModel:
    def invoke(self, messages):
        return AIMessage(content="ok")


class SimpleChatRuntimeTests(SimpleTestCase):
    def test_block_chat_does_not_call_removed_mcp_handler(self):
        result, is_ai_chat = BaseChatStep().get_block_result(
            message_list=[],
            chat_model=FakeChatModel(),
            paragraph_list=[],
            no_references_setting={"status": "ai_questioning"},
            problem_text="question",
        )

        self.assertTrue(is_ai_chat)
        self.assertEqual(result.content, "ok")
```

- [ ] **步骤 2：运行测试验证当前失败**

运行：

```bash
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  .venv/bin/python apps/manage.py test application.tests.SimpleChatRuntimeTests -v 2
```

预期：FAIL，报错包含 `AttributeError` 和 `_handle_mcp_request`。

- [ ] **步骤 3：删除非流式分支的 MCP/工具调用残留**

从 `get_block_result()` 删除以下仅服务已删除功能的代码：

```python
runtime_user_id = get_runtime_user_id(...)
all_tool_ids = list(set(...))
authorized_set = set(filter_authorized_ids("tool", ...))
mcp_result = self._handle_mcp_request(...)
if mcp_result:
    return mcp_result, True
```

保留直返段落、指定回答、未配置模型处理，最后的普通路径固定为：

```python
return chat_model.invoke(message_list), True
```

不得重新引入 `tools`、`application.flow`、`ToolExecutor`、MCP 适配器或仅为其存在的授权过滤。

- [ ] **步骤 4：运行回归测试和静态引用扫描**

运行：

```bash
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  .venv/bin/python apps/manage.py test application.tests.SimpleChatRuntimeTests -v 2
rg -n --glob '*.py' '_handle_mcp_request|get_tools|mcp_response_generator|ToolExecutor|from tools' apps/application apps/chat apps/common
```

预期：测试 PASS；扫描没有可执行保留链路中的工具/MCP 调用。

- [ ] **步骤 5：提交运行时修复**

```bash
git add apps/application/chat_pipeline/step/chat_step/impl/base_chat_step.py apps/application/tests.py
git commit -m "fix(问答): 删除非流式聊天的工具调用残留"
```

### 任务 10：为已裁剪 Provider 增加升级处置和可读错误

**文件：**

- 创建：`apps/models_provider/migrations/0002_disable_unsupported_providers.py`
- 修改：`apps/models_provider/tools.py:54-60`
- 修改：`apps/models_provider/serializers/model_serializer.py:107-125`
- 修改：`apps/models_provider/tests.py`

- [ ] **步骤 1：编写旧 Provider 的失败测试**

在 `apps/models_provider/tests.py` 添加不访问数据库的测试，规定未知或已删除 Provider 的错误必须是业务错误、包含 Provider 名称，不能泄露 `KeyError`：

```python
from django.test import SimpleTestCase

from common.exception.app_exception import AppApiException
from models_provider.tools import get_provider


class ProviderCompatibilityTests(SimpleTestCase):
    def test_removed_provider_has_readable_error(self):
        with self.assertRaisesRegex(AppApiException, "model_local_provider"):
            get_provider("model_local_provider")
```

- [ ] **步骤 2：运行测试验证当前失败**

运行：

```bash
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  .venv/bin/python apps/manage.py test models_provider.tests.ProviderCompatibilityTests -v 2
```

预期：FAIL，当前抛出裸 `KeyError: 'model_local_provider'`。

- [ ] **步骤 3：将未知 Provider 转为业务错误**

在 `get_provider()` 使用 `ModelProvideConstants.__members__.get(provider)` 查找。未找到时抛出 `AppApiException`，消息同时说明模型供应商已被本地精简内核移除，并包含当前 Provider 值：

```python
provider_enum = ModelProvideConstants.__members__.get(provider)
if provider_enum is None:
    raise AppApiException(400, _("Model provider {provider} is no longer supported").format(provider=provider))
return provider_enum.value
```

将 `ModelSerializer.model_to_dict()` 和 `Operate.is_valid()` 改为复用 `get_provider()`，禁止继续直接索引 `ModelProvideConstants[...]`。

- [ ] **步骤 4：新增前向数据迁移，停用旧模型而不改写凭据**

创建 `0002_disable_unsupported_providers.py`，依赖 `('models_provider', '0001_initial')`。迁移只处理 `provider != 'model_openai_provider'` 的 `Model`：

```python
def forwards(apps, schema_editor):
    Model = apps.get_model("models_provider", "Model")
    for model in Model.objects.exclude(provider="model_openai_provider").iterator():
        meta = dict(model.meta or {})
        meta["disabled_reason"] = "provider_removed_by_local_core"
        model.status = "ERROR"
        model.meta = meta
        model.save(update_fields=["status", "meta"])
```

反向迁移使用 `migrations.RunPython.noop`。不得删除模型行、不得伪造 OpenAI credential、不得修改已应用的 `0001_initial.py` 来解决已有数据库问题。

- [ ] **步骤 5：编写并执行迁移演练测试**

在 `apps/models_provider/tests.py` 添加 `TransactionTestCase`，用 `MigrationExecutor` 迁移到 `0001_initial`，插入 `model_local_provider` 记录，迁移到 `0002_disable_unsupported_providers`，断言：

```python
self.assertEqual(model.status, "ERROR")
self.assertEqual(model.meta["disabled_reason"], "provider_removed_by_local_core")
```

运行：

```bash
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  .venv/bin/python apps/manage.py test models_provider.tests -v 2
```

预期：Provider 可读错误测试与迁移演练均 PASS。

- [ ] **步骤 6：提交 Provider 升级修复**

```bash
git add apps/models_provider/migrations/0002_disable_unsupported_providers.py apps/models_provider/tools.py \
  apps/models_provider/serializers/model_serializer.py apps/models_provider/tests.py
git commit -m "fix(模型): 停用已裁剪 Provider 的历史记录"
```

### 任务 11：显式停用历史工作流数据并清理 Trigger 定时任务

**文件：**

- 创建：`apps/application/migrations/0015_disable_workflow_applications.py`
- 创建：`apps/knowledge/migrations/0012_mark_workflow_knowledge_unsupported.py`
- 修改：`apps/chat/serializers/chat.py:431-441`
- 修改：`apps/application/serializers/common.py:74-108`
- 修改：`apps/application/serializers/application.py:175-248`
- 修改：`apps/knowledge/serializers/knowledge.py:401-454`
- 修改：`apps/common/job/scheduler.py:1-12`
- 修改：`apps/application/tests.py`、`apps/knowledge/tests.py`

- [ ] **步骤 1：编写历史工作流应用的失败测试**

在 `apps/application/tests.py` 用测试数据库创建 `type='WORK_FLOW'` 的 `Application` 和已发布版本，调用聊天校验路径，断言它返回业务错误且信息包含“workflow applications are not supported”，而不是继续进入 `chat_simple()`：

```python
with self.assertRaisesRegex(ChatException, "workflow applications are not supported"):
    serializer.chat(instance, SystemToResponse())
```

同时添加创建请求校验：`type='WORK_FLOW'` 必须被拒绝，`type='SIMPLE'` 仍通过。

- [ ] **步骤 2：运行测试验证当前错误行为**

运行：

```bash
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  .venv/bin/python apps/manage.py test application.tests -v 2
```

预期：FAIL；当前工作流应用会越过类型检查进入简单聊天，且创建 serializer 仍接受 `WORK_FLOW`。

- [ ] **步骤 3：收缩运行时和创建契约到 SIMPLE**

做以下最小修改：

```python
# application/serializers/application.py
type = serializers.ChoiceField(choices=[ApplicationTypeChoices.SIMPLE])

# chat/serializers/chat.py，在 get_application() 后、chat_simple() 前
if chat_info.application.type != ApplicationTypeChoices.SIMPLE.value:
    raise ChatException(400, _("Workflow applications are not supported by the local core"))
```

同步使 `ChatInfo.get_application()` 对非 `SIMPLE` 立即抛出相同的 `ChatException`，保证嵌入聊天、恢复会话和普通聊天入口行为一致。将 `ApplicationCreateRequest` 改为直接使用 `ApplicationCreateSerializer.SimplateRequest`，删除要求 `work_flow` 的 OpenAPI 字段。

- [ ] **步骤 4：新增应用和知识库的前向迁移**

`0015_disable_workflow_applications.py` 依赖 `application.0014_applicationversion_knowledge_ids`，对 `Application.type='WORK_FLOW'`：

```python
Application.objects.filter(type="WORK_FLOW").update(is_publish=False)
ApplicationVersion.objects.filter(type="WORK_FLOW").update(
    mcp_enable=False,
    mcp_tool_ids=[],
    mcp_servers={},
    tool_enable=False,
    tool_ids=[],
    skill_tool_ids=[],
)
```

不得把工作流 JSON 转换为简单应用，也不得将其 `type` 改为 `SIMPLE`；保留记录以供管理员识别和手工迁移。

`0012_mark_workflow_knowledge_unsupported.py` 依赖 `knowledge.0011_delete_knowledgeaction`，对 `Knowledge.type=4` 在 `meta` 加入：

```python
meta["disabled_reason"] = "workflow_knowledge_removed_by_local_core"
```

在知识库详情、编辑、任务触发和命中测试入口读取该标记并返回 400 业务错误。不得删除原知识库、文档或 `KnowledgeWorkflow*` 行，避免无法恢复的用户数据损失。

- [ ] **步骤 5：在 scheduler 启动前清理遗留 Trigger job**

在 `apps/common/job/scheduler.py` 的 `scheduler.start()` 前使用可选导入清理 `DjangoJob`：

```python
try:
    from django_apscheduler.models import DjangoJob
    DjangoJob.objects.filter(id__startswith="trigger:").delete()
except Exception:
    pass
```

只删除 `trigger:` 前缀的已删除能力任务；不得清理 `clean_chat_log`、`client_access_num_reset` 或其他核心 scheduler job。为该清理提取一个小函数，方便 mock `DjangoJob.objects.filter(...).delete()` 并单测前缀限定。

- [ ] **步骤 6：执行应用、知识库与 scheduler 回归测试**

运行：

```bash
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  .venv/bin/python apps/manage.py test application.tests knowledge.tests -v 2
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  .venv/bin/python apps/manage.py makemigrations --check --dry-run
```

预期：历史工作流应用和知识库得到明确拒绝；新简单应用继续可创建；不产生未提交 migration。

- [ ] **步骤 7：提交历史数据处置修复**

```bash
git add apps/application apps/knowledge apps/chat/serializers/chat.py apps/common/job/scheduler.py
git commit -m "fix(裁剪): 显式停用历史工作流和触发器数据"
```

### 任务 12：移除所有可达的已删除能力入口

**文件：**

- 修改：`ui/src/layout/layout-header/top-about/index.vue`
- 修改：`ui/src/views/home/component/ResourceAggregation.vue`
- 修改：`ui/src/api/home-page/home.ts`
- 修改：`ui/src/views/home/component/QuickCreate.vue`
- 修改：`ui/src/views/application/index.vue`
- 修改：`ui/src/api/application/application.ts`
- 修改：`ui/src/router/modules/system.ts`
- 修改：`ui/src/views/system/resource-authorization/index.vue`
- 修改：`ui/src/views/system/resource-authorization/component/PermissionTable.vue`
- 修改：`ui/src/views/application/ApplicationSetting.vue`
- 修改：`ui/src/api/system-resource-management/application.ts`
- 修改：`ui/src/components/dynamics-form/items/model/provider-data.ts`
- 修改：`ui/src/components/dynamics-form/items/model/Model.vue`
- 修改：`ui/src/components/dynamics-form/constructor/items/ModelConstructor.vue`

- [ ] **步骤 1：先为路由和接口表建立失败检查脚本**

创建 `ui/scripts/check-local-core-surface.mjs`。脚本读取 `ui/src` 源文件并失败于以下可执行残留：

```js
const forbidden = [
  "name: 'trigger'",
  "router.push('/tool')",
  'getToolAggregation(',
  'importApplication(',
  'exportApplication(',
  '/text_to_speech',
  '/speech_to_text',
  '/play_demo_text',
  "SourceTypeEnum.TOOL",
  "resource: 'TOOL'",
]
```

脚本的扫描范围限定在保留入口、路由、应用设置和 API 客户端；不扫描 locale、注释、`references/agentkb/` 或历史迁移，防止把非执行文本误判为问题。

- [ ] **步骤 2：运行脚本验证当前失败**

运行：

```bash
cd ui
node scripts/check-local-core-surface.mjs
```

预期：FAIL，至少报告 Trigger 页头入口、首页工具聚合、应用导入/导出、TTS/STT 和 Tool 授权路由。

- [ ] **步骤 3：删除 Trigger、工具统计、导入/导出和 Tool 授权入口**

完成以下收口：

- 从 `top-about/index.vue` 删除 Trigger tooltip、按钮、`PermissionConst.TRIGGER_READ` 和不再使用的 `route`。
- 从 `ResourceAggregation.vue` 删除工具卡片、`toolAggregation`、`getToolAggregation()` 调用；从 `home.ts` 删除该 API。
- 从 `QuickCreate.vue`、应用列表创建菜单和卡片操作菜单删除应用导入/导出；从 `application.ts` 删除对应 API。
- 从 `system.ts` 删除工具授权父级权限和 `/system/authorization/tool` 子路由；从授权页和权限表删除 `SourceTypeEnum.TOOL` 选项及工具权限判断。

- [ ] **步骤 4：删除语音、MCP/工具设置和前端 Provider 静态数据**

保持浏览器端文字回答展示，但删除服务端语音与工具配置：

- 从 `ApplicationSetting.vue` 删除 STT/TTS 表单、试听、服务器语音调用、MCP、工具、技能、代理组合区块及其 imports、状态和初始化请求。
- 从 `application.ts`、`system-resource-management/application.ts` 删除 TTS/STT/MCP API 封装。
- 删除 `provider-data.ts` 中除 `model_openai_provider` 外的 Provider 条目；组件继续只按实际后端 `provider_list` 分组渲染。
- 同步移除不再使用的组件 imports，不能以固定权限返回 `false` 隐藏已删除能力。

- [ ] **步骤 5：执行表面检查与前端构建**

运行：

```bash
cd ui
node scripts/check-local-core-surface.mjs
pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat
```

预期：全部 PASS；构建后使用 `rg -n '/workflow|/mcp_tools|/text_to_speech|/speech_to_text|/play_demo_text' dist/assets`，结果不含已删除服务端端点。

- [ ] **步骤 6：提交前端契约收口**

```bash
git add ui/src ui/scripts/check-local-core-surface.mjs
git commit -m "fix(前端): 移除裁剪后不可用的功能入口"
```

### 任务 13：锁定依赖和 API 契约

**文件：**

- 修改：`.gitignore:190-192`
- 创建或修改：`uv.lock`
- 修改：`README-hr.md`
- 修改：`apps/application/api/application_api.py:21-23`

- [ ] **步骤 1：删除 `uv.lock` 忽略规则并生成锁文件**

从 `.gitignore` 移除单独的 `uv.lock` 行，然后运行：

```bash
uv lock
uv lock --check
uv sync --locked --dry-run
```

预期：锁文件包含 `pycryptodome` 的固定版本和 hash；所有命令退出码为 0。

- [ ] **步骤 2：验证 OpenAPI 不再要求工作流对象**

在 `apps/application/tests.py` 增加 schema 回归测试：

```python
request = ApplicationCreateAPI.get_request()
self.assertNotIn("work_flow", request().get_fields())
```

运行：

```bash
PYTHONPATH=apps SERVER_NAME=web DJANGO_SETTINGS_MODULE=maxkb.settings \
  .venv/bin/python apps/manage.py test application.tests -v 2
```

预期：PASS，创建 API 仅暴露简单应用实际需要的字段。

- [ ] **步骤 3：更新开发说明并提交**

在 `README-hr.md` 明确写入：

- 从未裁剪 v2 升级前必须备份 PostgreSQL，并在 staging 副本演练 migration。
- 已裁剪 Provider 会被标为 `ERROR`，须创建并重新绑定 OpenAI 兼容 LLM/Embedding。
- 工作流应用和工作流知识库被保留为历史数据但不可运行；必须在原版实例手工导出或重建为简单应用/基础知识库。
- 旧 Trigger job 会在启动 scheduler 前清理。
- 依赖安装必须使用 `uv sync --locked`。

提交：

```bash
git add .gitignore uv.lock README-hr.md apps/application/api/application_api.py apps/application/tests.py
git commit -m "chore(依赖): 锁定本地精简内核依赖"
```

### 任务 14：在全新库和 v2 升级副本上完成验收

**文件：**

- 修改：`README-hr.md`
- 修改：`docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md`

- [ ] **步骤 1：验证代码、Django 注册和 Provider 表面**

运行：

```bash
export MAXKB_CONFIG_TYPE=ENV
export SERVER_NAME=web
export DJANGO_SETTINGS_MODULE=maxkb.settings
export PYTHONPATH=apps
.venv/bin/python -m compileall -q apps main.py
.venv/bin/python apps/manage.py check
.venv/bin/python apps/manage.py makemigrations --check --dry-run
.venv/bin/python - <<'PY'
import django
django.setup()
from models_provider.constants.model_provider_constants import ModelProvideConstants
assert list(ModelProvideConstants.__members__) == ["model_openai_provider"]
print("provider registry: PASS")
PY
```

预期：所有命令通过；Provider 注册表仅包含 OpenAI。

- [ ] **步骤 2：执行全套回归测试和前端构建**

运行：

```bash
.venv/bin/python apps/manage.py test application.tests knowledge.tests models_provider.tests -v 2
cd ui
node scripts/check-local-core-surface.mjs
pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat
```

预期：测试和两套构建均 PASS。

- [ ] **步骤 3：演练真实 PostgreSQL 升级路径**

在隔离 PostgreSQL 数据库执行，不得对开发主库或生产库执行：

```bash
pg_dump --format=custom --file=/tmp/maxkb-v2-before-slim.dump <v2_staging_database>
python main.py upgrade_db
```

升级后以 SQL 检查迁移效果：

```sql
SELECT provider, status, meta->>'disabled_reason'
FROM model
WHERE provider <> 'model_openai_provider';

SELECT id, name, type, is_publish
FROM application
WHERE type = 'WORK_FLOW';

SELECT id, meta->>'disabled_reason'
FROM knowledge
WHERE type = 4;

SELECT id
FROM django_apscheduler_djangojob
WHERE id LIKE 'trigger:%';
```

预期：旧 Provider 状态为 `ERROR`；工作流应用均未发布；工作流知识库有禁用原因；最后一条查询无记录。记录数据库版本、迁移输出和四项查询结果到审计文档。

- [ ] **步骤 4：更新审计记录并提交验收证据**

```bash
git add README-hr.md docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md
git commit -m "test(裁剪): 验证精简内核升级兼容性"
```
