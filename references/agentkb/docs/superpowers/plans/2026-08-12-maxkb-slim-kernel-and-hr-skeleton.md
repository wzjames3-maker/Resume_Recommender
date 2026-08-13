# 子项目一：MaxKB 精简内核 + 人事模块骨架 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在产品仓库 `/home/wzjames/toC/maxkb`（MaxKB v2 fork）中完成精简内核：编排类入口不可见、知识库问答可用，并新增 `apps/hr` Django app 骨架与 Vue"人事部"菜单占位页。

**架构：** 以 MaxKB v2 为内核，前端隐藏工作流/工具/市场入口（只改 `ui/src/router` 与视图层，不删后端代码），后端新增 `apps/hr` app 并注册 `INSTALLED_APPS`，前端新增 `hr` 路由模块挂载三个占位页。

**技术栈：** Django 5.2、DRF、Vue 3、Vite、LangChain（MaxKB 自带）、PostgreSQL、Docker。

**执行环境：** 所有路径相对于 `/home/wzjames/toC/maxkb/`（MaxKB v2 fork，本计划任务 1 创建）。任务中的 commit 均在 `/home/wzjames/toC/maxkb` 仓库执行。

---

### 任务 1：获取 MaxKB v2 源码并建立基线

**文件：**
- 创建：`/home/wzjames/toC/maxkb/`（git clone 产物）
- 创建：`/home/wzjames/toC/maxkb/README-hr.md`（GPL 与派生说明）

- [ ] **步骤 1：clone MaxKB v2 到产品仓库**

```bash
cd /home/wzjames/toC && git clone --branch v2 --depth 1 https://github.com/1panel-dev/MaxKB.git maxkb
cd /home/wzjames/toC/maxkb && git log --oneline -1
```

预期：输出 v2 分支最新 commit hash，记录为基线。

- [ ] **步骤 2：记录基线与 GPL 派生说明**

创建 `/home/wzjames/toC/maxkb/README-hr.md`：

```markdown
# AgentKB-HR（基于 MaxKB v2 派生）

本仓库源自 MaxKB v2（GPL-3.0，https://github.com/1panel-dev/MaxKB）。
依据 GPL-3.0，本衍生仓库及其后续代码必须以 GPL-3.0 开源。
基线 commit：`<步骤 1 记录的 hash>`

## 裁剪范围（仅隐藏入口，不删除底层代码）
- 可视化工作流编排（前端路由层隐藏）
- MCP 工具库（前端菜单隐藏）
- 应用市场（前端视图层隐藏）
- 触发器（已上游隐藏）

## 新增模块
- apps/hr：人事业务 Django app（骨架）
- ui/src/views/hr：人事占位页
```

- [ ] **步骤 3：Commit 基线说明**

```bash
cd /home/wzjames/toC/maxkb && git add README-hr.md && git commit -m "docs: 记录 GPL 派生声明与裁剪范围"
```

预期：commit 成功，工作树干净。

### 任务 2：基线部署验证（精简前能力基线）

**文件：**
- 无代码修改，仅验证

- [ ] **步骤 1：构建并启动基线容器**

```bash
cd /home/wzjames/toC/maxkb/installer && docker build -t maxkb-hr:base -f Dockerfile ../
docker run -d --name maxkb-hr-base -p 8080:8080 \
  -e MAXKB_DB_HOST=host.docker.internal -e MAXKB_DB_PORT=5432 \
  -e MAXKB_DB_NAME=maxkb -e MAXKB_DB_USER=postgres -e MAXKB_DB_PASSWORD=MaxKB@123.. \
  maxkb-hr:base
```

先按 `installer/start-postgres.sh` 启动本地 PostgreSQL 依赖（或复用已有 PG 实例，`MAXKB_DB_HOST` 指向可访问地址）。

预期：容器启动，`curl -fsS http://localhost:8080/` 返回 HTML。

- [ ] **步骤 2：验证知识库上传与问答**

浏览器打开 `http://localhost:8080`，默认账号 `admin / MaxKB@123..`：

1. 登录成功。
2. 新建知识库 → 上传一个 `.txt` 或 `.md` 文档 → 分段/向量化完成。
3. 知识库对话中提问，能返回带引用来源的回答。

预期：3 步全部成功。这是后续裁剪验收的对照基线。

- [ ] **步骤 3：停止基线容器**

```bash
docker rm -f maxkb-hr-base
```

预期：容器删除成功。

### 任务 3：前端隐藏编排类入口

**文件：**
- 修改：`ui/src/router/routes.ts`
- 修改：`ui/src/router/modules/tool.ts`
- 修改：`ui/src/views/application/index.vue`

- [ ] **步骤 1：注释高级编排路由**

修改 `ui/src/router/routes.ts`，注释掉以下三个路由块（保留代码，仅隐藏）：

```typescript
  // 高级编排
  // {
  //   path: '/application/:from/:id/workflow',
  //   name: 'ApplicationWorkflow',
  //   meta: { activeMenu: '/application' },
  //   component: () => import('@/views/application-workflow/index.vue'),
  // },
  // 知识库工作流
  // {
  //   path: '/knowledge/:id/:folderId/workflow',
  //   name: 'KnowledgeWorkflow',
  //   meta: { activeMenu: '/knowledge' },
  //   component: () => import('@/views/knowledge-workflow/index.vue'),
  // },
  // {
  //   path: '/tool/:id/:folderId/workflow',
  //   ...
  // },
```

- [ ] **步骤 2：隐藏工具（MCP）菜单**

修改 `ui/src/router/modules/tool.ts`，在 `meta` 中增加 `hidden: true`（与 `trigger.ts` 同模式）：

```typescript
  meta: {
    title: 'views.tool.title',
    menu: true,
    hidden: true,
    ...
  },
```

- [ ] **步骤 3：隐藏应用市场入口**

在 `ui/src/views/application/index.vue` 中找到 `TemplateStoreDialog` 的引用（约 428 行 import 与模板中的 `<TemplateStoreDialog ... />` 及打开按钮），注释掉打开入口与组件挂载，保留 import 注释。

```vue
<!-- <TemplateStoreDialog ... /> -->
```

- [ ] **步骤 4：验证裁剪**

```bash
cd /home/wzjames/toC/maxkb/ui && npm ci && npm run build
```

预期：构建成功。浏览器导航无"工具"菜单、无应用市场入口；直接访问 `/application/1/1/workflow` 与 `/tool` 显示 404/空页。

- [ ] **步骤 5：Commit**

```bash
cd /home/wzjames/toC/maxkb && git add ui/src/router/routes.ts ui/src/router/modules/tool.ts ui/src/views/application/index.vue && git commit -m "feat: 前端隐藏工作流编排/工具/应用市场入口"
```

### 任务 4：新增 apps/hr Django app 骨架

**文件：**
- 创建：`apps/hr/__init__.py`
- 创建：`apps/hr/apps.py`
- 创建：`apps/hr/models/__init__.py`
- 创建：`apps/hr/migrations/__init__.py`
- 创建：`apps/hr/services/__init__.py`
- 修改：`apps/maxkb/settings/base/web.py`

- [ ] **步骤 1：创建目录与基础文件**

```bash
cd /home/wzjames/toC/maxkb && mkdir -p apps/hr/models apps/hr/migrations apps/hr/services
touch apps/hr/__init__.py apps/hr/models/__init__.py apps/hr/migrations/__init__.py apps/hr/services/__init__.py
```

创建 `apps/hr/apps.py`：

```python
from django.apps import AppConfig


class HrConfig(AppConfig):
    name = "hr"
    verbose_name = "人事模块"
```

- [ ] **步骤 2：注册 INSTALLED_APPS**

修改 `apps/maxkb/settings/base/web.py`，在 `INSTALLED_APPS` 列表末尾（`django_apscheduler` 之后）追加：

```python
    'hr.apps.HrConfig',
```

- [ ] **步骤 3：验证 app 可加载**

```bash
cd /home/wzjames/toC/maxkb && python manage.py check
```

预期：`System check identified no issues`。

- [ ] **步骤 4：生成并应用空迁移**

```bash
cd /home/wzjames/toC/maxkb && python manage.py makemigrations hr && python manage.py migrate hr
```

预期：生成 `apps/hr/migrations/0001_initial.py`（空迁移或仅含 app 记录），migrate 成功。

- [ ] **步骤 5：Commit**

```bash
cd /home/wzjames/toC/maxkb && git add apps/hr apps/maxkb/settings/base/web.py && git commit -m "feat: 新增 apps/hr Django app 骨架并注册"
```

### 任务 5：Vue"人事部"菜单与占位页

**文件：**
- 创建：`ui/src/views/hr/candidate/index.vue`
- 创建：`ui/src/views/hr/job/index.vue`
- 创建：`ui/src/views/hr/interview/index.vue`
- 创建：`ui/src/router/modules/hr.ts`

- [ ] **步骤 1：创建三个占位页**

`ui/src/views/hr/candidate/index.vue`：

```vue
<template>
  <div>
    <h2>候选人管理</h2>
    <p>人事模块占位页，第二阶段实现候选人列表与管理。</p>
  </div>
</template>
<script setup lang="ts"></script>
```

`ui/src/views/hr/job/index.vue` 与 `ui/src/views/hr/interview/index.vue` 同结构，标题分别改为"职位管理"、"面试管理"。

- [ ] **步骤 2：创建 hr 路由模块**

创建 `ui/src/router/modules/hr.ts`：

```typescript
const hrRouter = {
  path: '/hr',
  name: 'hr',
  meta: {
    title: '人事部',
    icon: 'app-user',
    group: 'workspace',
    order: 6,
  },
  redirect: '/hr/candidate',
  component: () => import('@/layout/layout-template/SimpleLayout.vue'),
  children: [
    {
      path: '/hr/candidate',
      name: 'hr-candidate',
      meta: { title: '候选人管理', activeMenu: '/hr' },
      component: () => import('@/views/hr/candidate/index.vue'),
    },
    {
      path: '/hr/job',
      name: 'hr-job',
      meta: { title: '职位管理', activeMenu: '/hr' },
      component: () => import('@/views/hr/job/index.vue'),
    },
    {
      path: '/hr/interview',
      name: 'hr-interview',
      meta: { title: '面试管理', activeMenu: '/hr' },
      component: () => import('@/views/hr/interview/index.vue'),
    },
  ],
}

export default hrRouter
```

- [ ] **步骤 3：验证构建与路由**

```bash
cd /home/wzjames/toC/maxkb/ui && npm run build
```

预期：构建成功。浏览器导航显示"人事部"菜单，候选人/职位/面试三个占位页可访问。

- [ ] **步骤 4：Commit**

```bash
cd /home/wzjames/toC/maxkb && git add ui/src/views/hr ui/src/router/modules/hr.ts && git commit -m "feat: 新增人事部菜单与占位页"
```

### 任务 6：集成验收

**文件：**
- 无业务代码修改；如需修复，修改前述文件

- [ ] **步骤 1：全量构建部署**

```bash
cd /home/wzjames/toC/maxkb/installer && docker build -t maxkb-hr:v1 -f Dockerfile ../
docker run -d --name maxkb-hr-v1 -p 8080:8080 \
  -e MAXKB_DB_HOST=host.docker.internal -e MAXKB_DB_PORT=5432 \
  -e MAXKB_DB_NAME=maxkb -e MAXKB_DB_USER=postgres -e MAXKB_DB_PASSWORD=MaxKB@123.. \
  maxkb-hr:v1
curl -fsS http://localhost:8080/
```

预期：容器启动，页面 200。

- [ ] **步骤 2：验收清单核对**

| 项 | 预期 |
|---|---|
| 登录 admin 默认账号 | 成功 |
| 知识库上传/分段/问答/引用 | 与任务 2 基线一致可用 |
| 导航无"工具 MCP"菜单 | 不可见 |
| 导航无应用市场入口 | 不可见 |
| 直接访问 `/tool`、`/application/1/1/workflow` | 404/空页 |
| 导航显示"人事部" | 可见 |
| `/hr/candidate`、`/hr/job`、`/hr/interview` | 三个占位页可访问 |
| `python manage.py check` | 无问题 |
| `python manage.py migrate hr` | 成功 |

- [ ] **步骤 3：停止验收容器并核对 diff**

```bash
docker rm -f maxkb-hr-v1
cd /home/wzjames/toC/maxkb && git status --short
```

预期：工作树仅含本计划 6 个 commit 的改动，无意外文件。

- [ ] **步骤 4：记录验收结果**

在 `/home/wzjames/toC/maxkb/README-hr.md` 末尾追加：

```markdown
## 子项目一验收（2026-08-12）
- 精简内核：通过（知识库上传/问答/引用可用，编排入口不可见）
- apps/hr 骨架：通过（INSTALLED_APPS 注册、migrate 成功）
- 人事部菜单与占位页：通过
```

并 commit：

```bash
cd /home/wzjames/toC/maxkb && git add README-hr.md && git commit -m "docs: 记录子项目一验收结果"
```