# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MaxKB (Max Knowledge Brain) fork: a slimmed MaxKB v2 core (RAG knowledge base) with an embedded multi-tenant HR recruitment workspace (ATS) in `apps/hr`. Backend is Python 3.11 / Django 5.2 / DRF; frontend is Vue 3 / Vite / Element Plus. Data layer is PostgreSQL + pgvector and Redis; Celery for async work. GPL-3.0. Upstream workflow engine / MCP / function library / multi-modal / local-model features were removed; see `README-hr.md` and `docs/PRD.md` for the actual product.

## Development Commands

The backend is driven by a single entrypoint `main.py` (not `manage.py` directly). It sets `apps/` on `sys.path` and configures Django settings, so module imports are `from application...`, `from common...` — not `from apps.application...`.

```bash
# Dev: runs collectstatic + migrate, then ONE service. You usually run both in separate terminals.
python main.py dev            # web      (Django runserver on 0.0.0.0:8080)
python main.py dev celery     # celery worker (queues: celery, model)

# Production-style start (spawns gunicorn + celery as watched daemons)
python main.py start all -d
python main.py start web -w 3      # gunicorn
python main.py start task          # celery_default + celery_model
python main.py stop all            # stop daemons
python main.py status              # daemon status

# Database / static
python main.py upgrade_db          # run migrations (has PG-crash-recovery retry logic)
python main.py collect_static      # collect static files (serves ui/dist)
python apps/manage.py makemigrations <app>
python apps/manage.py migrate

# i18n — .po files live in apps/locales/{en_US,zh_CN,zh_Hant}/LC_MESSAGES/
python apps/manage.py makemessages -l zh_Hant  # extract strings
python apps/manage.py compilemessages            # compile .po -> .mo (required at build time)
```

Frontend (`ui/`):
```bash
cd ui
npm install
npm run dev          # admin SPA (Vite dev server, proxies /admin/api & /chat/api -> :8080)
npm run chat         # chat embed SPA
npm run build        # build admin dist
npm run build-chat   # build chat dist
npm run lint         # eslint --fix
npm run type-check   # vue-tsc
```

Python linting: `ruff` (line-length 120, config in `pyproject.toml`). Tests: `uv run python apps/manage.py test hr.tests application.tests knowledge.tests models_provider.tests ops.tests --keepdb` (current baseline 301 tests; env vars in `HANDOFF.md` §1.1).

Dependencies are managed with `uv` (`uv.lock`, `pyproject.toml`). Python is pinned to `~=3.11.0`.

## Architecture

### Settings: single runtime

`apps/maxkb/settings/` is a single full Django app config in `base/web.py` (DB, cache, REST framework, all `INSTALLED_APPS`, templates, i18n); `settings/__init__.py` imports `base/*` (web + logging + auth + lib + mem). The former `base/model.py` local-embedding runtime was removed.

All runtime config comes from the `CONFIG` singleton (`apps/maxkb/const.py` + `conf.py`). `MAXKB_CONFIG_TYPE=ENV` reads `MAXKB_*` env vars (the `.env` file uses this); otherwise it loads YAML from `/opt/maxkb/conf`. `CONFIG.get_db_setting()` / `get_cache_setting()` build the DB and Redis configs (with optional Redis Sentinel support).

### URL layout

Two API surfaces, configured via `CONFIG.get_admin_path()` (default `/admin`) and `get_chat_path()` (default `/chat`):
- `/admin/api/*` — management API (users, tools, models_provider, folders, knowledge, system_manage, application, trigger, oss, homepage). Backed by DRF + drf-spectacular (Swagger at `/admin/api-doc`).
- `/chat/api/*` — runtime chat API (chat views). The MCP endpoint was removed (only an empty `chat/mcp/` package remains).

The Vue admin SPA and chat SPA are served as Django static files from `ui/dist` (`STATICFILES_DIRS`).

### Model provider abstraction (`apps/models_provider/`)

`IModelProvider` (abstract) -> OpenAI-compatible impl in `impl/openai_model_provider/` (the multi-vendor providers were removed during slimming). Each provider registers `ModelInfo` (model type + credential + model class) into `ModelInfoManage`. Model types include `LLM` and `EMBEDDING` (`ModelTypeConst`). To add a model, register `ModelInfo` with a `MaxKBBaseModel` subclass and a `BaseModelCredential`.

### Application & chat (`apps/application/`, `apps/chat/`)

An "application" is a configurable agent. The workflow engine and chat pipeline were removed during slimming; chat is served by the API views under `apps/chat/api/` (chat_api / chat_authentication_api / chat_embed_api / vote_api).

Streaming chat responses go through `BaseToResponse` (`apps/common/handle/base_to_response.py`) with three impls: `system_to_response` (MaxKB SSE protocol), `openai_to_response` (OpenAI-compatible), `loop_to_response`. SSE frames are `data: <json>\n\n`.

### RAG / knowledge (`apps/knowledge/`)

Documents are split into paragraphs; paragraphs are embedded and stored via `vector/pg_vector.py` (pgvector). Search hits the vector store then optionally a reranker model. Celery tasks under `knowledge/task/` handle document parsing/embedding.

### Async & scheduling (`apps/ops/`)

Celery app `ops.celery` (name `MaxKB`) with two queues: `celery` (general) and `model` (model/long tasks). Broker + result backend is Redis (sentinel-aware). Tasks use a custom `hmac_signed_serializer`. `@celery_app.task` decorated functions are autodiscovered from every `INSTALLED_APPS`. `django-apscheduler` and `django-celery-beat` provide scheduled jobs. `celery-once` provides single-execution locking.

### MCP

Removed during slimming. Only an empty `apps/chat/mcp/` package remains; no MCP endpoint is routed.

### Frontend (`ui/`)

Two SPAs built from the same repo: admin (`npm run build`) and chat embed (`npm run build-chat`), both into `ui/dist`. Markdown editor is md-editor-v3. Vite proxies `/admin/api` and `/chat/api` to `127.0.0.1:8080` in dev. Env files are in `ui/env/`.

### Sandbox

The untrusted-Python ctypes sandbox was removed during slimming. The only remaining sandbox is the Jinja2 `SandboxedEnvironment` used for template rendering (`apps/common/init/init_template.py`).

## Coding Conventions

- Python line length: **120** (`.editorconfig`, `pyproject.toml`, Copilot rules).
- **Minimize diffs.** Do not reformat entire files, reflow lines, or rename unless required. Make the smallest possible change and preserve existing structure/formatting. (`.github/copilot-instructions.md`)
- Match the existing module header style (most files begin with a `# coding=utf-8` block-style docstring with `@project/@Author/@file/@date/@desc`).
- UI code follows the existing Vue 3 Composition API + `<script setup>` + Element Plus patterns; lint with `npm run lint` before finishing.
