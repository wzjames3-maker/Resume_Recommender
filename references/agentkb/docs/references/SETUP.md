# MaxKB 复刻 — 环境搭建指南（SETUP）

> **这份文档是给谁的？**
> 你是一个会写 Python 后端、但从没搭过「前后端 + 数据库 + 缓存 + Docker」全栈项目的开发者。
> 跟着本文从上往下做，每一步都能直接复制粘贴。做完后，你本地能把整个项目跑起来。
>
> **预计耗时：** 第一次搭 60–90 分钟（大头是下载和编译）。搭好后，日常启动只要 1 分钟。
>
> **阅读约定：**
> - `$` 开头的行 = 你在终端里输入的命令（`$` 本身不要输入）。
> - 「预期输出」= 命令跑完应该看到的东西，用来确认成功。
> - 出现和预期不一样的输出，先停下来对照【第 6 节 常见问题排查】。

---

## 目录

1. [系统要求](#1-系统要求)
2. [必装工具](#2-必装工具逐项给安装命令--验证命令)
3. [项目依赖清单](#3-项目依赖清单)
4. [API Key 申请指南](#4-api-key-申请指南)
5. [本地开发环境启动](#5-本地开发环境启动)
6. [常见问题排查](#6-常见问题排查)
7. [目录结构说明](#7-目录结构说明)

---

## 1. 系统要求

在动手前，先确认你的电脑满足下面的条件。不满足的项会导致后面某一步卡死。

| 项目 | 要求 | 为什么 |
|------|------|--------|
| **操作系统** | Linux（推荐 Ubuntu 22.04+）/ macOS 13+ / Windows 用 WSL2 | Docker、Make、shell 脚本在类 Unix 环境最顺。Windows 原生不推荐。 |
| **内存（RAM）** | **最少 16GB** | embedding 模型、PostgreSQL、Docker、浏览器同时开，8GB 会卡到怀疑人生。 |
| **磁盘** | **至少 50GB 可用** | Docker 镜像（~5GB）+ `node_modules`（~1GB）+ Python 依赖 + 模型文件，都很占地方。 |
| **网络** | 能访问 PyPI、npm、Docker Hub、HuggingFace | 装依赖、拉镜像、下模型都要联网。国内网络见【第 6 节】的镜像方案。 |

### Windows 用户特别注意

如果你用 Windows，**先装 WSL2**，然后在 WSL2 的 Ubuntu 里按本文 Linux 的步骤走：

```bash
# 在 Windows PowerShell（管理员）里执行
$ wsl --install -d Ubuntu-22.04
```

装完重启，打开「Ubuntu」终端，之后所有 Linux 命令都在这里跑。

### 检查磁盘和内存

```bash
# 看磁盘剩余空间（Linux/macOS）
$ df -h /

# 看内存（Linux）
$ free -h

# 看内存（macOS）
$ sysctl hw.memsize
# 输出单位是字节，例如 hw.memsize: 17179869184，除以 1073741824 即为 GB（此例为 16GB）
$ echo $(( $(sysctl -n hw.memsize) / 1073741824 )) GB
# 预期输出：16 GB（或你的实际内存大小）
```

---

## 2. 必装工具（逐项给安装命令 + 验证命令）

> **顺序很重要**：请按下面的顺序装，因为后面的工具依赖前面的（比如 pnpm 依赖 Node）。
> 每个工具都给了 **Ubuntu** 和 **macOS** 两套命令，选你系统对应的那套。

### 2.1 Python 3.12+（用 pyenv 管理）

**为什么用 pyenv？** 不同项目可能要不同 Python 版本，pyenv 让你随时切换，不污染系统自带的 Python。

#### Ubuntu

```bash
# 第一步：装编译 Python 需要的系统库
$ sudo apt update
$ sudo apt install -y make build-essential libssl-dev zlib1g-dev libbz2-dev \
    libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev xz-utils \
    tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

# 第二步：装 pyenv
$ curl https://pyenv.run | bash

# 第三步：把 pyenv 加进 shell 配置（Ubuntu 默认是 bash）
$ echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
$ echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
$ echo 'eval "$(pyenv init -)"' >> ~/.bashrc

# 第四步：让配置生效
$ exec $SHELL

# 第五步：装 Python 3.12 并设为全局默认
$ pyenv install 3.12.7
$ pyenv global 3.12.7
```

#### macOS

```bash
# 先装 Homebrew（如果还没有）
$ /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 装 pyenv
$ brew update
$ brew install pyenv

# 加进 shell 配置（macOS 默认是 zsh）
$ echo 'eval "$(pyenv init -)"' >> ~/.zshrc
$ exec $SHELL

# 装 Python 3.12 并设为全局默认
$ pyenv install 3.12.7
$ pyenv global 3.12.7
```

#### 验证

```bash
$ python --version
# 预期输出：Python 3.12.7

$ which python
# 预期输出：路径里包含 .pyenv（例如 /home/你/.pyenv/shims/python）
```

> ⚠️ 如果 `python --version` 还是 3.10/3.11，说明 pyenv 没生效，重开一个终端再试。

---

### 2.2 uv（Python 包管理器，替代 pip）

**为什么用 uv？** 它用 Rust 写的，装依赖比 pip 快 10–100 倍，还能管理虚拟环境。本项目用它替代 `pip` + `venv`。

#### Ubuntu & macOS（命令一样）

```bash
$ curl -LsSf https://astral.sh/uv/install.sh | sh

# 让 PATH 生效
$ source ~/.bashrc   # macOS 用：source ~/.zshrc
```

#### 验证

```bash
$ uv --version
# 预期输出：uv 0.x.x（一个版本号即可）
```

---

### 2.3 Node.js 22+（用 nvm 管理）

**为什么需要 Node？** 前端（React）是 JavaScript 写的，得靠 Node 来构建和运行。
**为什么用 nvm？** 和 pyenv 一个道理——管理多个 Node 版本。

#### Ubuntu & macOS（命令一样）

```bash
# 第一步：装 nvm
$ curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash

# 第二步：让配置生效
$ exec $SHELL

# 第三步：装 Node 22（LTS 稳定版）并使用
# 注意：不要装 Node 20 —— Node 20 已于 2026 年 4 月 EOL（停止维护）
$ nvm install 22
$ nvm use 22
$ nvm alias default 22
```

#### 验证

```bash
$ node --version
# 预期输出：v22.x.x

$ npm --version
# 预期输出：10.x.x
```

---

### 2.4 pnpm（Node 包管理器）

**为什么用 pnpm？** 比 npm 省磁盘、装得快（依赖共享 + 硬链接）。本项目前端用它。

#### Ubuntu & macOS（命令一样）

```bash
# 方式一（推荐）：用 Node 自带的 corepack 启用
$ corepack enable
$ corepack prepare pnpm@latest --activate

# 方式二（如果 corepack 不好使）：直接用 npm 装
$ npm install -g pnpm
```

#### 验证

```bash
$ pnpm --version
# 预期输出：10.x.x（9.x.x 也可以）
```

> ⚠️ **pnpm 10.x 行为变化**：pnpm 10 起**不再自动执行依赖的构建脚本**（如 `postinstall`）。
> `pnpm install` 后如果看到 `Ignored build scripts` 之类的提示，运行 `pnpm approve-builds` 按提示批准
> （esbuild 等依赖需要构建脚本才能正常工作），否则可能出现依赖装上了但跑不起来的情况。

---

### 2.5 Docker + Docker Compose v2

**为什么需要 Docker？** 它把 PostgreSQL、Redis 这些服务装进「容器」里，一条命令启动，不污染你的系统，也不会出现「在我电脑上是好的」这种问题。

#### Ubuntu

```bash
# 用官方脚本一键安装
$ curl -fsSL https://get.docker.com | sudo sh

# 把当前用户加进 docker 组（这样不用每次都 sudo）
$ sudo usermod -aG docker $USER

# 让组权限生效（或者干脆退出重新登录）
$ newgrp docker
```

#### macOS

macOS 上装 **Docker Desktop**（图形界面，自带 Compose）：

```bash
$ brew install --cask docker
```

装完后**打开一次 Docker Desktop 应用**（在启动台里点那个鲸鱼图标），让它完成初始化。第一次启动要等一会儿。

#### 验证（两个系统一样）

```bash
$ docker --version
# 预期输出：Docker version 2x.x.x

$ docker compose version
# 预期输出：Docker Compose version v2.x.x
# ⚠️ 注意是 "docker compose"（中间空格），不是老的 "docker-compose"（中间横杠）

$ docker run hello-world
# 预期输出：看到 "Hello from Docker!" 字样，说明 Docker 能正常拉镜像、跑容器
```

> ⚠️ 如果报 `Cannot connect to the Docker daemon`，说明 Docker 服务没启动。看【第 6 节】。

---

### 2.6 Git

**为什么需要 Git？** 版本控制，记录每次代码改动，多人协作的基础。

#### Ubuntu

```bash
$ sudo apt install -y git
```

#### macOS

```bash
$ brew install git
# （macOS 通常已自带，也可用 xcode-select --install 获得）
```

#### 验证 + 初始配置

```bash
$ git --version
# 预期输出：git version 2.x.x

# 首次使用必须配置身份（把下面换成你自己的）
$ git config --global user.name "你的名字"
$ git config --global user.email "你的邮箱@example.com"
```

---

### 2.7 Make

**为什么需要 Make？** 项目把常用命令（启动、测试、迁移）封装成 `make xxx`，敲起来短。

#### Ubuntu

```bash
$ sudo apt install -y make
```

#### macOS

macOS 一般已随 Xcode 命令行工具自带。如果没有：

```bash
$ xcode-select --install   # 弹窗点「安装」
# 或者
$ brew install make
```

#### 验证

```bash
$ make --version
# 预期输出：GNU Make 4.x（或类似版本号）
```

---

### 2.8 curl / httpie（API 测试）

**为什么需要？** 用来直接给后端 API 发请求，验证接口通不通，不用每次都开浏览器。

#### curl

绝大多数系统已自带，直接验证：

```bash
$ curl --version
# 预期输出：curl 8.x.x ...
```

#### httpie（可选但推荐，输出更好看）

```bash
# Ubuntu / macOS 通用：用 uv 装成独立工具
$ uv tool install httpie

# 或者 macOS 用 brew
$ brew install httpie
```

验证：

```bash
$ http --version
# 预期输出：3.x.x
```

---

### 2.9 可选：数据库图形界面（pgAdmin / DBeaver）

**不是必须的**。命令行也能查数据库，但有个图形界面看表、写 SQL 更直观。二选一即可。

#### pgAdmin（PostgreSQL 专用，免费）

- **Ubuntu**：去 https://www.pgadmin.org/download/pgadmin-4-apt/ 按官方 apt 步骤装，或直接用 Docker 版。
- **macOS**：

```bash
$ brew install --cask pgadmin4
```

#### DBeaver（支持多种数据库，社区版免费）

- **Ubuntu**：去 https://dbeaver.io/download/ 下 `.deb` 包安装。
- **macOS**：

```bash
$ brew install --cask dbeaver-community
```

装好后，连接信息用 `.env` 里的数据库地址（默认 `localhost:5432`，库名/用户/密码见 `.env`）。

---

### 2.10 工具清单速查表

全部装完后，跑一遍下面的命令，确认都就位：

```bash
$ python --version && uv --version && node --version && pnpm --version \
    && docker --version && docker compose version && git --version && make --version
```

只要每行都有正常版本号、没有 `command not found`，就可以进入下一节。

---

## 3. 项目依赖清单

> 这一节告诉你「项目用了哪些第三方库、每个是干嘛的」。
> **你不需要手动逐个装它们**——第 5 节的 `uv sync` / `pnpm install` 会自动读取清单并安装。
> 这里列出来是为了让你心里有数，面试时也能讲清楚「为什么选它」。

### 3.1 后端依赖（`backend/pyproject.toml`）

#### 运行时依赖

| 包名 | 版本 | 用途（为什么需要它） |
|------|------|----------------------|
| `fastapi` | `~0.115` | **Web 框架**。接收 HTTP 请求、返回 JSON，是整个后端的骨架。 |
| `uvicorn[standard]` | `~0.30` | **ASGI 服务器**。真正跑 FastAPI 应用的进程，`[standard]` 带上高性能依赖。 |
| `sqlalchemy[asyncio]` | `~2.0` | **ORM**。用 Python 类操作数据库，不用手写 SQL；`[asyncio]` 启用异步支持。 |
| `asyncpg` | `~0.29` | **PostgreSQL 异步驱动**。SQLAlchemy 通过它连数据库。 |
| `alembic` | `~1.13` | **数据库迁移**。表结构变更版本化管理，可升级可回滚。 |
| `pydantic-settings` | `~2.4` | **配置管理**。从环境变量/`.env` 读取配置并做类型校验。 |
| `celery[redis]` | `~5.4` | **异步任务队列**。文档解析这种耗时活儿丢后台跑，不阻塞 HTTP 请求。 |
| `redis` | `~5.0` | **Redis 客户端**。连缓存 / Celery Broker / token 黑名单。 |
| `python-jose[cryptography]` | `~3.3` | **JWT 生成与校验**。登录后发的 token 就靠它。 |
| `passlib[bcrypt]` | `~1.7` | **密码哈希**。密码绝不存明文，存 bcrypt 哈希。 |
| `pymupdf` | `~1.24` | **PDF 解析**。从 PDF 里提取文字。 |
| `httpx` | `~0.27` | **HTTP 客户端**。后端去调 embedding / LLM 的 API 用它。 |
| `pgvector` | `~0.3` | **向量扩展的 Python 绑定**。让 SQLAlchemy 能读写 pgvector 的 `vector` 类型。 |
| `python-multipart` | `~0.0.9` | **文件上传支持**。FastAPI 处理 `multipart/form-data` 需要它。 |
| `tiktoken` | `~0.7` | **Token 计数**。文档切片（chunking）时按 token 精确统计和控制切片长度。 |
| `sentence-transformers` | `~3.0` | **本地 rerank 模型**。加载开源重排模型对检索结果精排。⚠️ 会连带安装 torch，下载约 2GB。 |
| `prometheus-client` | `~0.20` | **指标监控（W8）**。暴露 Prometheus 格式的监控指标（接口耗时、任务量等）。 |

#### 开发/测试依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| `pytest` | `~8.3` | **测试框架**。写和跑单元测试、集成测试。 |
| `pytest-asyncio` | `~0.24` | 让 pytest 能测 `async` 异步函数。 |
| `pytest-cov` | `~5.0` | 统计测试覆盖率（测到了多少代码）。 |
| `httpx` | `~0.27` | 测试里用它模拟发请求给 FastAPI。 |
| `ruff` | `~0.6` | **Linter + 格式化**。查代码风格问题，极快。 |
| `mypy` | `~1.11` | **静态类型检查**。提前发现类型错误。 |

### 3.2 前端依赖（`frontend/package.json`）

| 包名 | 版本 | 用途（为什么需要它） |
|------|------|----------------------|
| `react` | `^18.3` | **UI 库**。用组件拼界面。 |
| `react-dom` | `^18.3` | 把 React 组件渲染到浏览器 DOM 上。 |
| `react-router-dom` | `^6.26` | **前端路由**。不同 URL 显示不同页面。 |
| `typescript` | `^5.5` | **类型系统**。给 JS 加类型，少犯低级错误。 |
| `vite` | `^5.4` | **构建工具 + 开发服务器**。启动快、热更新快。 |
| `@vitejs/plugin-react` | `^4.3` | 让 Vite 支持 React（JSX + 快速刷新）。 |
| `zustand` | `^4.5` | **状态管理**。跨组件共享数据（如登录用户信息），比 Redux 轻。 |
| `axios` | `^1.7` | **HTTP 客户端**。前端调后端 API。 |
| `react-markdown` | `^9` | **Markdown 渲染**。把 AI 回复的 Markdown 渲染成漂亮排版。 |
| `remark-gfm` | `^4` | 给 `react-markdown` 加表格、任务列表等扩展语法支持。 |
| `react-syntax-highlighter` | `^15.5` | **代码语法高亮**。AI 回复里的代码块按语言高亮渲染。 |
| `@types/react-syntax-highlighter` | `^15.5` | `react-syntax-highlighter` 的类型定义。 |
| `sonner` | `^1.5` | **Toast 通知**。操作成功/失败的轻量弹窗提示。 |
| `tailwindcss` | `^3.4` | **样式方案**。用工具类快速写 CSS，不手写大段样式表。 |
| `postcss` | `^8.4` | CSS 处理管线，Tailwind 编译所需的底层依赖。 |
| `autoprefixer` | `^10.4` | 自动补浏览器兼容前缀，Tailwind 配套工具。 |
| `clsx` | `^2.1` | **条件拼接 class**。按条件动态组合多个类名。 |
| `tailwind-merge` | `^2.5` | **解决 Tailwind 类名冲突**。合并类名时让后者正确覆盖前者。 |
| `vitest` | `^2` | **前端测试框架**。和 Vite 深度集成。 |
| `@testing-library/react` | `^16` | 测试 React 组件的工具库。 |
| `eslint` | `^9` | **前端 Linter**。查 JS/TS 代码问题。 |
| `prettier` | `^3` | **代码格式化**。统一代码风格。 |
| `@types/react` | `^18.3` | React 的类型定义。 |
| `@types/react-dom` | `^18.3` | React DOM 的类型定义。 |
| `@types/node` | `^22` | Node.js 的类型定义。 |
| `@playwright/test` | `^1.47` | **E2E 测试**。模拟真实浏览器操作，端到端验证关键流程。 |

---

## 4. API Key 申请指南

本项目要调用大模型 API 做两件事：

1. **Embedding（向量化）**：把文字变成一串数字（向量），用来做语义检索。
2. **LLM（大语言模型）**：根据检索到的内容生成回答。

你可以选 **OpenAI** 或 **通义千问（阿里）**，二选一即可。国内网络推荐通义千问，更稳。

### 4.1 方案 A：OpenAI

- **申请地址**：https://platform.openai.com
- **注册** → 登录后进入 **API keys** 页面 → 点 **Create new secret key** → 复制保存（只显示一次）。
- **用到的模型**：
  - LLM：`gpt-4o`
  - Embedding：`text-embedding-3-small`
- **注意**：需要能访问 OpenAI 的网络环境；新账号通常要绑定支付方式才能用。

> ⚠️ **本项目向量维度固定为 1024。使用 OpenAI `text-embedding-3-small` 时必须传 `dimensions=1024` 参数；使用通义 `text-embedding-v3` 默认即为 1024 维。推荐使用 BGE-M3（开源、1024 维、中文优秀）。**

### 4.2 方案 B：通义千问（阿里云百炼 / DashScope）

- **申请地址**：https://dashscope.console.aliyun.com
- **注册阿里云账号** → 开通「百炼 / DashScope」→ 在控制台创建 **API-KEY** → 复制保存。
- **控制台说明**：DashScope 已并入阿里云百炼，也可直接在百炼控制台 https://bailian.console.aliyun.com 开通服务、创建和管理 API-KEY。
- **用到的模型**：
  - LLM：`qwen-max`
  - Embedding：`text-embedding-v3`
- **优点**：国内直连、有免费额度、中文效果好。

### 4.3 费用预估

| 场景 | 大约花费 |
|------|----------|
| **开发调试**（自己一个人玩） | **约 $5–10 / 月** |
| **生产上线**（有真实用户） | **约 $50–100 / 月** |

> 开发阶段调用量很小，主要花在自己反复测试上。可以在控制台设置**用量上限/告警**，防止超支。

### 4.4 如何配置 Key（重要）

**永远不要把 API Key 写进代码，也不要提交到 Git。** 正确做法是放进 `.env` 文件：

```bash
# 在 backend 目录，从模板复制一份
$ cp backend/.env.example backend/.env

# 用编辑器打开 backend/.env，填入你的 key
```

`backend/.env` 里大概长这样（**示例值为 compose 容器内可用值，密钥请替换为你自己的**）：

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/agentkb
REDIS_URL=redis://redis:6379/0
JWT_SECRET=<用 `openssl rand -hex 32` 生成>
MODEL_KEY_ENC_KEY=<64 位十六进制随机串>
```

> 说明：`db` / `redis` 是 `docker-compose.yml` 中的服务名，容器网络内可直接访问；数据库名为 `agentkb`（对应 compose 的 `POSTGRES_DB`）。根目录不存在 `.env` / `.env.example`，Compose 只读取 `backend/.env`。

> ⚠️ **本项目向量维度固定为 1024。使用 OpenAI `text-embedding-3-small` 时必须传 `dimensions=1024` 参数；使用通义 `text-embedding-v3` 默认即为 1024 维。推荐使用 BGE-M3（开源、1024 维、中文优秀）。**

**为什么安全？** `.env` 已经被写进 `.gitignore`，Git 不会跟踪它。提交到仓库的只有不含真实值的 `.env.example` 模板。

> ⚠️ 自查：跑 `git status`，如果看到 `.env` 出现在列表里，说明它没被忽略，**先别提交**，检查 `.gitignore`。

---

## 5. 本地开发环境启动

> 前提：第 2 节的工具都装好了，第 4 节的 API Key 也拿到了。
> 下面 8 步按顺序执行。

### 第 1 步：克隆仓库

```bash
$ git clone <你的仓库地址> maxkb-replica
$ cd maxkb-replica
```

> 把 `<你的仓库地址>` 换成真实地址，例如 `git@github.com:yourname/maxkb-replica.git`。

### 第 2 步：创建并填写环境变量

```bash
$ cp backend/.env.example backend/.env
# 用你喜欢的编辑器打开 backend/.env，填入第 4 节申请的 API Key
```

### 第 3 步：安装后端依赖

```bash
# 在项目根目录执行
$ cd backend && uv sync
```

`uv sync` 会读取 `pyproject.toml`，把后端依赖全部装进 uv 管理的虚拟环境。

### 第 4 步：安装前端依赖

```bash
# 接上一步，从 backend 目录进入 frontend 目录
$ cd ../frontend && pnpm install
```

> 如果你已经回到项目根目录，则执行 `cd frontend && pnpm install`。
> 装完如看到构建脚本被忽略的提示，按 2.4 节说明运行 `pnpm approve-builds`。

### 第 5 步：启动基础服务（PostgreSQL + Redis）

```bash
$ make up
```

这条命令实际执行 `docker compose up -d db redis`，**只启动基础设施容器（数据库 db、缓存 redis），不会启动应用服务本身**——应用由第 7 步的 `make dev` 在本地启动。

验证容器都起来了：

```bash
$ docker compose ps
# 预期输出：db、redis 两个容器状态为 running / healthy
# （注意：这里没有 app 容器，属于正常现象）
```

### 第 6 步：执行数据库迁移（建表）

```bash
$ make migrate
```

这条命令实际执行 `alembic upgrade head`，把数据库表结构建好。

预期输出里能看到类似 `Running upgrade ... -> head` 的字样。

### 第 7 步：启动后端 + 前端（开发模式）

```bash
$ make dev
```

这条命令会同时启动：
- 后端：FastAPI（默认 `http://localhost:8000`，容器内启动并自动执行 `alembic upgrade head`）
- 前端：Vite 开发服务器（默认 `http://localhost:5173`）

### 第 8 步：验证

**验证后端：**

```bash
$ curl http://localhost:8000/health
# 预期输出：{"status":"ok"}
```

**验证前端：** 浏览器打开 http://localhost:5173，能看到页面即成功。

> ✅ 到这一步，你的本地开发环境就跑起来了。日常开发只需要 `make up` + `make dev`。

---

## 6. 常见问题排查

遇到报错先别慌，下表覆盖了 90% 的新手问题。按「现象 → 原因 → 解决」对照处理。

| # | 现象（报错信息） | 原因 | 解决办法 |
|---|------------------|------|----------|
| 1 | `Cannot connect to the Docker daemon` | Docker 服务没启动 | **Linux**：`sudo systemctl start docker`（并 `sudo systemctl enable docker` 设开机自启）。**macOS**：打开 Docker Desktop 应用，等状态栏鲸鱼图标变稳定。**WSL2**：确认 Docker Desktop 里勾选了「Use the WSL 2 based engine」。 |
| 2 | `port is already allocated` / 5432 端口被占用 | 本机已有一个 PostgreSQL 在跑 | 先找出占用进程：`sudo lsof -i :5432`。是本地装的 PG 就停掉：`sudo systemctl stop postgresql`；或改 `docker-compose.yml` 里的端口映射（如 `5433:5432`），同时更新 `.env` 的 `DATABASE_URL`。 |
| 3 | `extension "vector" is not found` | 数据库没装 pgvector 扩展 | 确认用的是带 pgvector 的镜像 `pgvector/pgvector:pg16`（而非普通 `postgres:16-alpine`）。然后进库执行 `CREATE EXTENSION IF NOT EXISTS vector;`，或确认首个 Alembic 迁移里已包含这条语句。 |
| 4 | `npm install` / `pnpm install` 很慢或失败 | 默认 npm 源在国外 | 切到国内镜像：`pnpm config set registry https://registry.npmmirror.com`，然后重新 `pnpm install`。 |
| 5 | HuggingFace 模型下载失败 / 超时 | 国内访问 HF 受限 | 设置镜像后再跑：`export HF_ENDPOINT=https://hf-mirror.com`（可写进 `.env` 或 shell 配置）。 |
| 6 | 浏览器报 CORS 错误（`Access-Control-Allow-Origin`） | 前端域名不在后端允许列表 | 检查后端 CORS 配置，确保 `allow_origins` 里包含 `http://localhost:5173`。开发环境要放开，生产环境再收紧。 |
| 7 | Celery worker 连不上 Redis | Redis 没起 / 地址不对 | 先 `docker compose ps` 确认 redis 在跑；再核对 `.env` 的 `REDIS_URL` 是否为 `redis://localhost:6379/0`；在容器网络内则用服务名（如 `redis://redis:6379/0`）。 |
| 8 | `pyenv install` 编译报错 | 缺系统依赖 | 回到 2.1，确认 Ubuntu 的第一步依赖装全了，再重跑 `pyenv install 3.12.7`。 |
| 9 | `make: command not found` | 没装 Make | 回到 2.7 安装。 |
| 10 | 前端能打开但接口全 404/连不上 | 后端没起或端口不对 | 确认 `make dev` 里后端在跑，`curl http://localhost:8000/health` 能通；核对前端代理配置指向 8000。 |
| 11 | `uv sync` 装 Python 依赖慢或失败 | 默认 PyPI 源在国外 | 切国内镜像：`export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`（可写进 `~/.bashrc` / `~/.zshrc`），再重跑 `uv sync`。 |
| 12 | `docker pull` 拉镜像失败 / 超时 | 国内访问 Docker Hub 受限 | 配置镜像加速器：编辑 `/etc/docker/daemon.json`（Linux）或 Docker Desktop → Settings → Docker Engine（macOS），加入云厂商提供的 `registry-mirrors` 地址，然后重启 Docker。 |
| 13 | 公司网络下 docker / curl 全报网络错误 | 公司代理未正确配置 | 检查 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量；Docker 需单独配代理（Docker Desktop → Resources → Proxies；Linux 配 systemd 或 `~/.docker/config.json`），curl 走系统环境变量即可。 |
| 14 | Windows 浏览器访问不了 WSL2 里的服务 | WSL2 网络隔离，端口未转发 | 在 Windows PowerShell（管理员）执行 `netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=<WSL2的IP>`（IP 用 `wsl hostname -I` 查看）。 |
| 15 | 后端启动时出现 passlib + bcrypt 告警（如 `error reading bcrypt version`） | passlib 与新版 bcrypt 不兼容 | 告警无害，不影响功能，可忽略；想消除就在 `pyproject.toml` 里钉版本 `bcrypt<4.1`。 |
| 16 | `git clone` 报 `Permission denied (publickey)` | 没配 SSH key | 改用 HTTPS 克隆：`git clone https://github.com/yourname/maxkb-replica.git`。 |

> 还是解决不了？把**完整报错信息**复制下来，连同 `docker compose ps`、`python --version`、`node --version` 的输出一起提问，能大大加快定位。

---

## 7. 目录结构说明

下面是项目的完整目录结构，逐个说明「这里放什么、为什么这么放」。

```text
maxkb-replica/
├── backend/                    # 后端（FastAPI + Python）
│   ├── app/                    # 应用主代码
│   │   ├── api/                # 路由层：定义 HTTP 端点，只做参数接收和响应
│   │   ├── core/               # 核心基础设施：配置、数据库连接、安全、日志
│   │   ├── models/             # ORM 模型：对应数据库表结构
│   │   ├── schemas/            # Pydantic 模型：请求/响应的数据校验
│   │   ├── services/           # 业务逻辑层：真正干活的地方
│   │   ├── tasks/              # Celery 异步任务（文档解析等耗时操作）
│   │   └── rag/                # RAG 核心：解析、切片、embedding、检索
│   ├── alembic/                # 数据库迁移脚本（Alembic 生成）
│   ├── tests/                  # 后端测试
│   ├── pyproject.toml          # Python 依赖清单（见 3.1）
│   └── Dockerfile              # 后端镜像构建说明
│
├── frontend/                   # 前端（React + TypeScript）
│   ├── src/
│   │   ├── api/                # 封装对后端的 axios 请求
│   │   ├── components/         # 可复用的 UI 组件
│   │   ├── pages/              # 页面级组件（对应路由）
│   │   ├── stores/             # Zustand 状态管理
│   │   ├── hooks/              # 自定义 React Hooks
│   │   └── main.tsx            # 前端入口
│   ├── package.json            # Node 依赖清单（见 3.2）
│   └── vite.config.ts          # Vite 配置（含开发代理）
│
├── docs/                       # 文档（本文件就在这里）
├── scripts/                    # 一次性/运维脚本（部署、备份等）
├── nginx/                      # Nginx 配置（生产环境反向代理用）
├── .github/
│   └── workflows/              # GitHub Actions CI/CD 配置
│
├── docker-compose.yml          # 本地多服务编排（db + redis + app ...）
├── Makefile                    # 常用命令快捷方式（make up/dev/test/...）
├── .env.example                # 环境变量模板（提交到 Git）
├── .env                        # 你的真实环境变量（不提交到 Git）
├── .gitignore                  # 告诉 Git 忽略哪些文件
└── README.md                   # 项目门面：介绍 + 快速启动
```

### 为什么 `backend/` 和 `frontend/` 分开？

- 两者语言、依赖、构建方式完全不同，分开后各自独立开发、独立部署。
- 前端只通过 HTTP API 和后端通信，接口是唯一的耦合点，边界清晰。

### 为什么 `app/` 里要分 `api / services / models` 这几层？

- **`api/`** 只管「接收请求、返回响应」，不写业务逻辑。
- **`services/`** 写业务逻辑，方便单独测试，不依赖 HTTP。
- **`models/`** 只描述数据结构。
- 这样分层后，改一处不会牵连全身，测试也好写。

### 为什么 `rag/` 单独一层？

- RAG（检索增强生成）是本项目的核心能力，逻辑复杂（解析、切片、向量化、检索、重排）。
- 单独成目录，方便演进和替换其中某个环节（比如换个 embedding 模型）。

### `.env.example` 和 `.env` 的区别？

- `.env.example`：**模板**，只有字段名和占位值，**提交到 Git**，让新人知道要填什么。
- `.env`：**你的真实配置**（含 API Key、密码），**被 `.gitignore` 忽略，绝不提交**。

---

## 附：日常命令速查

| 命令 | 作用 |
|------|------|
| `make up` | 启动 Docker 里的基础服务（仅 db、redis，不含应用服务） |
| `make down` | 停止并移除这些服务 |
| `make migrate` | 执行数据库迁移 |
| `make dev` | 启动后端 + 前端开发服务器 |
| `make test` | 跑测试 |
| `make lint` | 代码风格检查 |
| `docker compose ps` | 查看容器状态 |
| `docker compose logs -f <服务名>` | 实时看某个服务的日志 |

> 搞定！环境有问题随时回【第 6 节】对照。祝开发顺利。
