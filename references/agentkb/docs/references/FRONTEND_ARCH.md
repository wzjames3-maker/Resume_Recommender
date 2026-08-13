# 前端架构设计文档（FRONTEND_ARCH.md）

> 项目：MaxKB Replica —— 多租户 RAG 知识库问答平台
> 技术栈：React 18 + TypeScript + Vite + Zustand + TailwindCSS + React Router
> 包管理器：**pnpm**（全局约定，禁止混用 npm/yarn）
> 文档目标：开发者可直接依据本文档完成前端实现，无需再做架构决策。

---

## 1. 技术选型理由

### 1.1 为什么选 React（而不是 Vue）

| 维度 | React | Vue | 结论 |
|------|-------|-----|------|
| 生态系统 | 组件库/工具链最丰富（shadcn/ui、TanStack 系列、react-markdown 等） | 生态良好但偏中文圈 | React 胜 |
| TypeScript 支持 | JSX 天然贴合 TS 类型推导，社区类型定义最完善 | Vue 3 SFC 类型支持已大幅改善，但复杂泛型场景仍弱于 React | React 胜 |
| 就业市场 | 全球岗位数量约为 Vue 的 3 倍，学习成果可迁移性最强 | 国内岗位较多 | 本项目面向自学与通用性，React 胜 |
| 流式渲染场景 | 细粒度 setState + hooks 组合对 SSE 流式更新友好 | 同样可行 | 持平 |

**决策**：本项目包含大量流式聊天渲染、文件上传、复杂表单交互，React 的 hooks 组合模型与 TS 类型推导配合最佳。

### 1.2 为什么选 Zustand（而不是 Redux）

- **API 极简**：一个 `create` 函数定义 store，无 action type 字符串常量、无 reducer switch、无 provider 包裹。
- **样板代码少**：Redux Toolkit 仍需 `createSlice` + `configureStore` + `Provider` + `useSelector`/`useDispatch` 分离；Zustand 一行 `useAuthStore(s => s.user)` 即可。
- **规模匹配**：本项目全局状态仅 3 个 store（auth / knowledgeBase / chat），状态树浅、派生逻辑少，不需要 Redux 的中间件体系（thunk/saga）与 DevTools 时间旅行。
- **无 Provider 嵌套**：Zustand 基于 hook 订阅，避免 Redux `<Provider>` 与 React Router 嵌套带来的层级问题。
- **天然支持组件外访问**：axios 拦截器中可直接 `useAuthStore.getState()` 读写 token，Redux 则需额外导出 store 实例。

**决策**：在"够用即最优"原则下选择 Zustand。若未来状态复杂度上升（如离线协作编辑），可平滑迁移至 Zustand + middleware（persist/devtools），无需换框架。

### 1.3 为什么选 TailwindCSS

- **utility-first**：样式直接写在 JSX 的 `className` 中，杜绝 CSS 文件命名（BEM）、作用域、死代码清理问题。
- **零 CSS 文件管理**：本项目无自定义 CSS 文件（仅 `index.css` 引入 Tailwind 指令），构建产物体积小（PurgeCSS 自动 tree-shake 未使用类）。
- **设计一致性**：间距（`p-4`）、颜色（`blue-600`）、圆角（`rounded-lg`）全部来自固定刻度，避免"魔法数字"，多人协作风格统一。
- **与组件库兼容**：后续可无缝引入 shadcn/ui（基于 Tailwind + Radix），加速 UI 开发。

### 1.4 为什么选 Vite

- **极速 HMR**：基于原生 ESM 的按需编译，冷启动 < 500ms，热更新 < 50ms，开发体验远优于 Webpack。
- **ESM 原生**：开发服务器直接利用浏览器 ES Module，无需打包即可调试；生产构建用 Rollup，产物优化成熟。
- **配置简单**：`vite.config.ts` 一个文件搞定代理（`/api/v1` → 后端）、别名（`@/` → `src/`）、环境变量（`VITE_*` 前缀）。
- **TypeScript 开箱即用**：内置 esbuild 转译 TS，无需额外配置 babel。

---

## 2. 目录结构

```
frontend/src/
├── api/                    ← axios 实例 + 全部 API 函数（按领域分文件）
│   ├── client.ts           ← axios 实例，含请求/响应拦截器（JWT 刷新、统一错误处理）
│   ├── auth.ts             ← login / register / refresh / logout / getMe（GET /users/me）
│   ├── knowledgeBase.ts    ← 工作区列表、KB CRUD（KB 端点嵌套在 workspaces 路径下，见 API_SPEC §4.4）
│   ├── documents.ts        ← 文档上传、列表、详情、分块、retry、删除
│   └── chat.ts             ← POST /chat（SSE 流式）、会话 CRUD、历史消息
├── components/             ← 可复用 UI 组件（无路由依赖）
│   ├── ui/                 ← Button, Input, Modal, Spinner, Toast, Badge, Empty
│   ├── layout/             ← Sidebar, Header, MainLayout（含 <Outlet/>）
│   ├── chat/               ← ChatWindow, MessageBubble, StreamingText, SourceCard, ConversationList
│   └── documents/          ← UploadZone, DocumentList, ChunkPreview, StatusBadge
├── pages/                  ← 路由级页面（只做数据编排，UI 下沉到 components）
│   ├── LoginPage.tsx
│   ├── RegisterPage.tsx
│   ├── DashboardPage.tsx
│   ├── KnowledgeBasePage.tsx
│   ├── DocumentsPage.tsx
│   ├── ChatPage.tsx
│   └── SettingsPage.tsx
├── stores/                 ← Zustand stores（全局状态唯一来源）
│   ├── authStore.ts
│   ├── knowledgeBaseStore.ts
│   └── chatStore.ts
├── hooks/                  ← 自定义 hooks
│   ├── useSSE.ts           ← Server-Sent Events / ReadableStream 流式接收
│   ├── useAuth.ts          ← 路由守卫逻辑（RequireAuth 组件使用）
│   └── useUpload.ts        ← 文件上传（进度、取消、重试）
├── types/                  ← TypeScript 接口定义（与后端 API 契约一一对应，snake_case）
│   └── index.ts
├── utils/                  ← 纯函数工具
│   ├── format.ts           ← 文件大小、日期格式化
│   ├── cn.ts               ← className 合并（clsx + tailwind-merge）
│   ├── scroll.ts           ← 引用定位：滚动到来源卡片并高亮
│   └── poll.ts             ← 通用轮询工具
├── App.tsx                 ← 路由配置（createBrowserRouter + RouterProvider）
└── main.tsx                ← 入口：挂载 React、引入 Tailwind
```

**约定**：
- 组件文件用 PascalCase（`MessageBubble.tsx`），hooks/stores/utils 用 camelCase。
- `pages/` 中的组件不允许被其他组件 import；`components/` 之间可自由互相引用。
- 所有 API 调用必须经过 `api/` 层，组件内禁止直接使用 axios/fetch（SSE 流式请求是唯一例外，见 6.2）。
- **字段命名**：前端类型与状态直接使用后端 snake_case 字段名，不做 camelCase 转换。
- **分页拆包**：列表端点统一返回 `{total, page, page_size, items}`（API_SPEC §1.5），api 层负责拆包——默认只返回 `items` 给 store；页面需要 `total` 做分页 UI 时，api 函数返回完整包裹对象。
- **ID 类型**：所有 ID 为 `number`（int64，API_SPEC §1.8），禁止用 string。

---

## 3. 路由表

使用 `react-router-dom@6` 的 `createBrowserRouter`，配合 `loader` 无关的纯客户端鉴权守卫（`RequireAuth` 组件）。

| Path | Page | Auth Required | Description |
|------|------|:---:|-------------|
| `/login` | `LoginPage` | ✗（已登录则重定向 `/`） | 邮箱 + 密码登录 |
| `/register` | `RegisterPage` | ✗（已登录则重定向 `/`） | 注册新租户账号；注册成功后重定向 `/login`（register 只返回 `user_id`，不自动登录） |
| `/` | `DashboardPage` | ✓ | 知识库列表（卡片式），创建 KB 入口 |
| `/kb/:id` | `KnowledgeBasePage` | ✓ | 单个 KB 详情：只读配置（embedding_model、chunk_size/chunk_overlap）+ 统计（doc_count / chunk_count）；仅 name / description 可编辑（API 不支持修改 embedding 配置，无 KB 级成员管理） |
| `/kb/:id/documents` | `DocumentsPage` | ✓ | KB 文档管理：上传、列表、分段预览、失败重试 |
| `/chat/:conversationId?` | `ChatPage` | ✓ | 对话页；无 `conversationId` 时为新会话（新会话必须先选择知识库） |
| `/settings` | `SettingsPage` | ✓ | 个人资料（昵称编辑，PUT /users/me）、退出登录 |
| `*` | `NotFoundPage` | ✗ | 404 兜底 |

**路由结构**：

```tsx
// App.tsx
const router = createBrowserRouter([
  { path: '/login', element: <GuestOnly><LoginPage /></GuestOnly> },
  { path: '/register', element: <GuestOnly><RegisterPage /></GuestOnly> },
  {
    element: <RequireAuth><MainLayout /></RequireAuth>,   // MainLayout 内含 <Outlet/>
    children: [
      { path: '/', element: <DashboardPage /> },
      { path: '/kb/:id', element: <KnowledgeBasePage /> },
      { path: '/kb/:id/documents', element: <DocumentsPage /> },
      { path: '/chat/:conversationId?', element: <ChatPage /> },
      { path: '/settings', element: <SettingsPage /> },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
]);
```

`RequireAuth`：读取 `authStore.isAuthenticated`，为 false 时 `<Navigate to="/login" state={{ from: location }} />`，登录成功后跳回原路径。

---

## 4. 组件树（ASCII art）

### 4.1 整体布局骨架

```
<App>
└── <RouterProvider>
    ├── <LoginPage> / <RegisterPage>          （无布局壳）
    └── <RequireAuth>
        └── <MainLayout>
            ├── <Sidebar>                     ← 左侧导航（Dashboard/Chat/Settings）
            │   ├── <Logo>
            │   ├── <NavLinks>
            │   └── <UserMenu>                ← 头像下拉：设置 / 退出
            ├── <Header>                      ← 面包屑 + 页面标题 + 全局操作
            └── <main>
                └── <Outlet/>                 ← 路由页面渲染位置
```

### 4.2 DashboardPage（知识库列表）

```
<DashboardPage>
├── <PageHeader title="知识库" action={<Button>新建知识库</Button>}>
├── <CreateKBModal>                            ← 条件渲染
│   └── <Input 名称/> <Input 描述/> <Input chunk_size/chunk_overlap/> <Button/>
│       （embedding 模型固定 bge-m3，创建后不可改，无需选择）
└── <KBGrid>
    └── <KBCard> × N
        ├── <Badge>分块配置 / 更新时间</Badge>
        └── <Link to={`/kb/${id}`}>
```

### 4.3 DocumentsPage（文档管理）

```
<DocumentsPage>
├── <UploadZone>                               ← 拖拽区 + 进度条列表
│   └── <UploadProgressItem> × N              ← 文件名 / 进度 / 状态
├── <DocumentList>
│   └── <DocumentRow> × N
│       ├── <StatusBadge status="pending|processing|ready|failed">
│       ├── 文件名 / 大小 / 分段数 / 创建时间
│       └── <RowActions> [预览分段] [重试（仅 failed）] [删除]
└── <ChunkPreviewDrawer>                       ← 条件渲染
    └── <ChunkItem> × N                        ← 分段内容 / position / token_count
```

### 4.4 ChatPage（核心页面）

```
<ChatPage>
├── <ConversationList>                         ← 左侧会话列表（移动端可折叠）
│   ├── <KBSelect/>                            ← 新会话必须先选择知识库（会话按 knowledge_base_id 过滤）
│   ├── <Button>新对话</Button>
│   └── <ConversationItem> × N
├── <ChatWindow>                               ← 中部消息区
│   ├── <MessageList>
│   │   └── <MessageBubble role="user|assistant"> × N
│   │       └── <MarkdownRenderer>             ← react-markdown + remark-gfm
│   │           └── <CodeBlock>                ← 语法高亮
│   ├── <StreamingText>                        ← isStreaming 时渲染流式气泡
│   │   └── <CitationButton [1][2]>            ← 引用角标
│   └── <ChatInput>                            ← 输入框 + 发送按钮（Enter 发送，Shift+Enter 换行）
└── <SourcePanel>                              ← 右侧来源面板（桌面端显示）
    └── <SourceCard id={`source-card-${i}`}> × N ← 文档名 / 内容片段 / 相似度分数
```

---

## 5. 状态设计（Zustand Stores）

### 5.1 类型定义（types/index.ts，节选）

> **前端类型直接使用后端 snake_case 字段名，不做转换**；所有 ID 为 `number`（int64）。

```typescript
export interface User {
  id: number;
  email: string;
  nickname: string;
  created_at: string;
}

export interface KnowledgeBase {
  id: number;
  workspace_id: number;
  name: string;
  description: string;
  embedding_model: string;   // 固定 bge-m3，创建后不可修改
  chunk_size: number;
  chunk_overlap: number;
  doc_count?: number;        // 详情端点 GET /knowledge-bases/{id} 返回
  chunk_count?: number;      // 详情端点返回
  created_at: string;
  updated_at: string;
}

export interface Document {
  id: number;
  knowledge_base_id: number;
  filename: string;
  file_size: number;         // 字节
  // pending/processing/ready/failed 为后端状态；uploading 为前端专有本地状态（上传中，尚未落库）
  status: 'uploading' | 'pending' | 'processing' | 'ready' | 'failed';
  chunk_count: number;
  error_message?: string;    // 仅 status == "failed" 时非空（详情端点返回）
  created_at: string;
  updated_at?: string;       // 列表端点不返回
}

export interface Chunk {
  id: number;
  document_id: number;
  content: string;
  token_count: number;
  position: number;          // 在文档中的序号，从 0 开始
  created_at: string;
}

export interface Conversation {
  id: number;
  knowledge_base_id: number;
  user_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant';
  content: string;
  token_count: number;
  sources: Source[];         // role == "user" 时为空数组
  created_at: string;
}

export interface Source {
  chunk_id: number;
  document_id: number;
  filename: string;
  content_snippet: string;
  score: number;             // 相似度分数 0~1
}

export interface CreateKBInput {
  name: string;
  description?: string;
  embedding_model?: string;  // 默认 bge-m3
  chunk_size?: number;       // 默认 500（100~2000）
  chunk_overlap?: number;    // 默认 50（0~500，且 < chunk_size）
}
```

### 5.2 authStore

```typescript
// stores/authStore.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import * as authApi from '@/api/auth';
import type { User } from '@/types';

const REFRESH_TOKEN_KEY = 'maxkb_refresh_token';

// refresh_token 优先存内存，localStorage 仅作页面刷新兜底（不放进 zustand persist）
let refreshTokenInMemory: string | null = null;

function readRefreshToken(): string | null {
  return refreshTokenInMemory ?? localStorage.getItem(REFRESH_TOKEN_KEY);
}

function storeRefreshToken(token: string | null) {
  refreshTokenInMemory = token;
  token
    ? localStorage.setItem(REFRESH_TOKEN_KEY, token)
    : localStorage.removeItem(REFRESH_TOKEN_KEY);
}

interface AuthState {
  accessToken: string | null;
  user: User | null;
  isAuthenticated: boolean;

  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, nickname: string) => Promise<void>;
  logout: () => void;
  refreshToken: () => Promise<void>;
  setUser: (user: User) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      user: null,
      isAuthenticated: false,

      login: async (email, password) => {
        // 登录响应只有令牌对，没有用户信息
        const { access_token, refresh_token } = await authApi.login(email, password);
        storeRefreshToken(refresh_token);
        set({ accessToken: access_token });
        const user = await authApi.getMe();        // GET /api/v1/users/me 拉取用户信息
        set({ user, isAuthenticated: true });
      },

      register: async (email, password, nickname) => {
        await authApi.register(email, password, nickname);   // 只返回 {user_id}，不自动登录
        // 注册成功后由 RegisterPage 重定向到 /login
      },

      logout: () => {
        const rt = readRefreshToken();
        if (rt) authApi.logout(rt).catch(() => {});   // refresh_token 放 JSON body，尽力吊销，失败忽略
        storeRefreshToken(null);
        set({ accessToken: null, user: null, isAuthenticated: false });
      },

      refreshToken: async () => {
        const rt = readRefreshToken();
        if (!rt) throw new Error('NO_REFRESH_TOKEN');
        const { access_token } = await authApi.refresh(rt);   // JSON body: {refresh_token}
        set({ accessToken: access_token });
      },

      setUser: (user) => set({ user }),
    }),
    {
      name: 'auth-storage',
      partialize: (s) => ({ accessToken: s.accessToken, user: s.user, isAuthenticated: s.isAuthenticated }),
    }
  )
);
```

**要点**：
- `accessToken` 通过 `persist` 存入 localStorage，刷新页面不丢失登录态。
- `refresh_token` 走 **JSON body** 方案（不使用 cookie）：refresh 与 logout 均以 `{refresh_token}` 请求体发送；前端存于内存，localStorage 仅作页面刷新兜底。
- 登录流程：`POST /auth/login` 只返回令牌对 → 再调 `GET /api/v1/users/me` 获取用户信息。
- 注册流程：`POST /auth/register` 只返回 `user_id` → 不自动登录，RegisterPage 重定向 `/login`。
- `refreshToken()` 供 axios 拦截器调用（见 6.1）。

### 5.3 knowledgeBaseStore

```typescript
// stores/knowledgeBaseStore.ts
import { create } from 'zustand';
import * as kbApi from '@/api/knowledgeBase';
import * as docApi from '@/api/documents';
import type { KnowledgeBase, Document, Chunk, CreateKBInput } from '@/types';

interface KBState {
  knowledgeBases: KnowledgeBase[];
  currentKB: KnowledgeBase | null;
  documents: Document[];
  chunks: Chunk[];
  loading: boolean;

  fetchKBs: () => Promise<void>;
  fetchKB: (id: number) => Promise<void>;
  createKB: (data: CreateKBInput) => Promise<KnowledgeBase>;
  updateKB: (id: number, data: { name?: string; description?: string }) => Promise<void>;
  deleteKB: (id: number) => Promise<void>;

  fetchDocuments: (kbId: number) => Promise<void>;
  uploadDocument: (
    kbId: number,
    file: File,
    opts?: { signal?: AbortSignal; onProgress?: (pct: number) => void }
  ) => Promise<number>;
  deleteDocument: (docId: number) => Promise<void>;
  retryDocument: (docId: number) => Promise<void>;
  fetchChunks: (docId: number) => Promise<void>;
  updateDocumentStatus: (docId: number, status: Document['status']) => void;
}

export const useKBStore = create<KBState>()((set, get) => ({
  knowledgeBases: [],
  currentKB: null,
  documents: [],
  chunks: [],
  loading: false,

  fetchKBs: async () => {
    set({ loading: true });
    try {
      // GET /workspaces/{ws_id}/knowledge-bases，api 层已拆包 items
      const knowledgeBases = await kbApi.list();
      set({ knowledgeBases });
    } finally {
      set({ loading: false });
    }
  },

  fetchKB: async (id) => {
    const currentKB = await kbApi.get(id);   // 详情含 doc_count / chunk_count
    set({ currentKB });
  },

  createKB: async (data) => {
    const kb = await kbApi.create(data);     // POST /workspaces/{ws_id}/knowledge-bases
    set({ knowledgeBases: [kb, ...get().knowledgeBases] });
    return kb;
  },

  updateKB: async (id, data) => {
    // PUT /knowledge-bases/{id}：仅 name / description 可改，embedding 等配置创建后不可变
    const kb = await kbApi.update(id, data);
    set({
      knowledgeBases: get().knowledgeBases.map((k) => (k.id === id ? { ...k, ...kb } : k)),
      currentKB: get().currentKB?.id === id ? { ...get().currentKB!, ...kb } : get().currentKB,
    });
  },

  deleteKB: async (id) => {
    await kbApi.remove(id);
    set({ knowledgeBases: get().knowledgeBases.filter((k) => k.id !== id) });
  },

  fetchDocuments: async (kbId) => {
    const documents = await docApi.list(kbId);   // api 层已拆包 items
    set({ documents });
  },

  uploadDocument: async (kbId, file, opts) => {
    // 1) 先以 uploading（前端专有状态）插入本地临时文档，上传期间列表可见
    const tempId = -Date.now();
    const temp: Document = {
      id: tempId,
      knowledge_base_id: kbId,
      filename: file.name,
      file_size: file.size,
      status: 'uploading',
      chunk_count: 0,
      created_at: new Date().toISOString(),
    };
    set({ documents: [temp, ...get().documents] });

    try {
      // 2) 202: {document_id, status: "pending"} —— 响应不含文件元信息，沿用本地文件信息
      const { document_id } = await docApi.upload(kbId, file, opts);
      set({
        documents: get().documents.map((d) =>
          d.id === tempId ? { ...d, id: document_id, status: 'pending' } : d
        ),
      });
      return document_id;   // 调用方（useUpload）用它启动状态轮询（见 6.3）
    } catch (err) {
      set({ documents: get().documents.filter((d) => d.id !== tempId) });   // 上传失败移除临时项
      throw err;
    }
  },

  deleteDocument: async (docId) => {
    await docApi.remove(docId);
    set({ documents: get().documents.filter((d) => d.id !== docId) });
  },

  retryDocument: async (docId) => {
    const { status } = await docApi.retry(docId);   // 202: {document_id, status: "processing"}
    get().updateDocumentStatus(docId, status);      // 随后由页面轮询直到 ready / failed
  },

  fetchChunks: async (docId) => {
    const chunks = await docApi.listChunks(docId);  // GET /documents/{id}/chunks，api 层已拆包 items
    set({ chunks });
  },

  updateDocumentStatus: (docId, status) => {
    set({
      documents: get().documents.map((d) => (d.id === docId ? { ...d, status } : d)),
    });
  },
}));
```

### 5.4 chatStore

```typescript
// stores/chatStore.ts
import { create } from 'zustand';
import * as chatApi from '@/api/chat';
import type { Conversation, Message, Source } from '@/types';

interface ChatState {
  conversations: Conversation[];
  currentConversation: Conversation | null;
  messages: Message[];
  isStreaming: boolean;

  // 流式中间态（不落库，仅渲染用）
  streamingContent: string;
  sources: Source[];

  fetchConversations: (kbId: number) => Promise<void>;
  selectConversation: (id: number) => Promise<void>;
  createConversation: (kbId: number) => Promise<Conversation>;
  deleteConversation: (id: number) => Promise<void>;

  sendMessage: (content: string) => Promise<void>;
  appendStreamChunk: (chunk: string) => void;
  setSources: (sources: Source[]) => void;
  finalizeStream: () => void;
  abortStream: () => void;
}

let abortController: AbortController | null = null;

export const useChatStore = create<ChatState>()((set, get) => ({
  conversations: [],
  currentConversation: null,
  messages: [],
  isStreaming: false,
  streamingContent: '',
  sources: [],

  fetchConversations: async (kbId) => {
    // GET /conversations?knowledge_base_id=...，kbId 为必填参数
    const conversations = await chatApi.listConversations(kbId);
    set({ conversations });
  },

  selectConversation: async (id) => {
    get().abortStream();   // 切换会话前先中止进行中的流
    // 后端没有 GET /conversations/{id} 端点，会话对象直接取自列表数据
    const conversation = get().conversations.find((c) => c.id === id) ?? null;
    const messages = await chatApi.listMessages(id);
    set({ currentConversation: conversation, messages, streamingContent: '', sources: [] });
  },

  createConversation: async (kbId) => {
    const conversation = await chatApi.createConversation(kbId);
    set({
      conversations: [conversation, ...get().conversations],
      currentConversation: conversation,
      messages: [],
    });
    return conversation;
  },

  deleteConversation: async (id) => {
    get().abortStream();   // 删除会话前先中止进行中的流
    await chatApi.deleteConversation(id);
    const conversations = get().conversations.filter((c) => c.id !== id);
    const cleared = get().currentConversation?.id === id
      ? { currentConversation: null, messages: [] }
      : {};
    set({ conversations, ...cleared });
  },

  sendMessage: async (content) => {
    const conv = get().currentConversation;
    // 新会话必须先选择知识库并 createConversation（ChatPage 负责该流程）
    if (!conv) throw new Error('NO_CONVERSATION');

    const userMsg: Message = {
      id: -Date.now(),      // 临时消息用负数 id，真实 id 由后端消息历史提供
      conversation_id: conv.id,
      role: 'user',
      content,
      token_count: 0,
      sources: [],
      created_at: new Date().toISOString(),
    };

    abortController = new AbortController();
    set({
      messages: [...get().messages, userMsg],
      isStreaming: true,
      streamingContent: '',
      sources: [],
    });

    try {
      await chatApi.streamChat(
        {
          knowledge_base_id: conv.knowledge_base_id,   // POST /chat 必带知识库 id
          conversation_id: conv.id,
          message: content,
        },
        {
          signal: abortController.signal,
          onSources: (sources) => set({ sources }),                       // 先于 token 到达
          onToken: (text) => set({ streamingContent: get().streamingContent + text }),
          onDone: (done) => {
            // done 携带 {message_id, token_count, conversation_id}；
            // 完整回答 = token 事件累积的 streamingContent
            const assistantMsg: Message = {
              id: done.message_id,
              conversation_id: done.conversation_id,
              role: 'assistant',
              content: get().streamingContent,
              token_count: done.token_count,
              sources: get().sources,
              created_at: new Date().toISOString(),
            };
            set({
              messages: [...get().messages, assistantMsg],
              isStreaming: false,
              streamingContent: '',
            });
          },
          onError: (err) => {
            set({ isStreaming: false, streamingContent: '' });
            throw err;
          },
        }
      );
    } finally {
      abortController = null;
    }
  },

  appendStreamChunk: (chunk) => set({ streamingContent: get().streamingContent + chunk }),
  setSources: (sources) => set({ sources }),

  finalizeStream: () => set({ isStreaming: false, streamingContent: '' }),

  abortStream: () => {
    abortController?.abort();
    set({ isStreaming: false, streamingContent: '' });
  },
}));
```

**要点**：
- `streamingContent` 是**中间态**：流式过程中只更新它，`done` 事件后才用累积内容 + `done.message_id` 构造完整消息 push 进 `messages`，避免重复渲染。
- `sources` 事件**先于** `token` 到达（见 6.2），来源卡片可先渲染。
- `abortController` 放模块级变量而非 state，因为它不需要触发渲染。
- 临时 `userMsg` 用负数 id（ID 为 number，不能用字符串前缀）。
- 切换 / 删除会话前必须先 `abortStream()`，避免旧会话的流写入新状态。
- `POST /chat` 必带 `knowledge_base_id`：新会话必须先选择知识库并 `createConversation` 才能发送。

---

## 6. 关键实现细节

### 6.1 JWT 拦截器（axios）

```typescript
// api/client.ts
import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '@/stores/authStore';

export const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  timeout: 30_000,
});

// ---- 请求拦截器：附加 Authorization ----
client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ---- 响应拦截器：401 自动刷新 + 重放原请求 ----
let refreshing: Promise<void> | null = null;   // 并发去重：多个 401 只刷新一次

client.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean };

    // 非 401、或刷新接口本身失败、或已重试过 → 直接抛出
    if (error.response?.status !== 401 || original.url?.includes('/auth/refresh') || original._retried) {
      return Promise.reject(error);
    }

    try {
      // 并发请求同时 401 时，共享同一个刷新 Promise（refresh_token 以 JSON body 发送）
      refreshing ??= useAuthStore.getState().refreshToken().finally(() => {
        setTimeout(() => { refreshing = null; }, 0);
      });
      await refreshing;

      original._retried = true;
      original.headers.Authorization = `Bearer ${useAuthStore.getState().accessToken}`;
      return client(original);                    // 用新 token 重放原请求
    } catch {
      // refresh 也失败 → 登出并跳转登录页
      useAuthStore.getState().logout();
      window.location.href = '/login';
      return Promise.reject(error);
    }
  }
);
```

**流程图**：

```
请求发出 ──► 附加 Bearer token ──► 后端
                                      │
                              200 ◄───┴───► 401
                               │              │
                             返回数据      是否刷新接口本身 401？
                                           │是        │否
                                        登出跳转   已有刷新进行中？──是──► await 共享 Promise
                                                      │否                    │
                                                   发起 refresh              │
                                                   （body 带 refresh_token）  │
                                                      │◄─────────────────────┘
                                               成功？──否──► 登出跳转 /login
                                                 │是
                                           重放原请求（_retried 标记防死循环）
```

### 6.2 SSE 流式渲染

后端协议（与 API_SPEC §5 一致）：`POST /api/v1/chat`，请求体
`{knowledge_base_id, conversation_id?, message, stream: true}`。
每条 SSE 事件为一行 `data: ` JSON，事件序列为 **`sources`（1 次，先于 token）→ `token`（N 次）→ `done`（1 次）**，`error` 可能在任意时刻出现并关闭连接。字段一律 snake_case：

```
data: {"type":"sources","sources":[{"chunk_id":5023,"document_id":401,"filename":"产品手册.pdf","content_snippet":"管理员密码重置：进入设置 → 安全 → 重置密码……","score":0.91}]}
data: {"type":"token","content":"您"}
data: {"type":"token","content":"可以"}
data: {"type":"token","content":"在设置页重置密码。"}
data: {"type":"done","message_id":7012,"token_count":45,"conversation_id":601}
```

| type | 载荷字段 | 说明 |
|------|----------|------|
| `sources` | `sources: [{chunk_id, document_id, filename, content_snippet, score}]` | 检索来源，推送一次，先于第一个 token |
| `token` | `content: str` | 增量文本片段，按生成顺序推送 |
| `done` | `message_id: number, token_count: number, conversation_id: number` | 流结束标志，必须是最后一条事件 |
| `error` | `code: str, message: str` | 流中断错误，出现后连接关闭 |

**为什么用 fetch + ReadableStream 而不是 EventSource**：EventSource 只支持 GET，无法携带自定义 `Authorization` 头；fetch 方案可 POST + 自定义 header，且能用 AbortController 中止。

```typescript
// api/chat.ts（流式部分）
import { useAuthStore } from '@/stores/authStore';
import type { Source } from '@/types';

export interface ChatStreamRequest {
  knowledge_base_id: number;
  conversation_id?: number;   // 不传则服务端自动创建会话
  message: string;
}

export interface StreamDone {
  message_id: number;
  token_count: number;
  conversation_id: number;
}

export interface StreamCallbacks {
  signal: AbortSignal;
  onSources: (sources: Source[]) => void;
  onToken: (text: string) => void;
  onDone: (done: StreamDone) => void;
  onError: (err: Error) => void;
}

export async function streamChat(body: ChatStreamRequest, cb: StreamCallbacks): Promise<void> {
  const res = await fetch(
    `${import.meta.env.VITE_API_BASE_URL ?? '/api/v1'}/chat`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${useAuthStore.getState().accessToken}`,
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({ ...body, stream: true }),
      signal: cb.signal,
    }
  );

  if (!res.ok || !res.body) {
    cb.onError(new Error(`Stream failed: ${res.status}`));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';                 // 最后一行可能不完整，留到下一轮

      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const event = JSON.parse(line.slice(5).trim());

        switch (event.type) {
          case 'sources': cb.onSources(event.sources); break;   // 先到一次，立即渲染来源卡片
          case 'token':   cb.onToken(event.content); break;     // 增量文本，累积到 streamingContent
          case 'done':    cb.onDone(event); return;             // {message_id, token_count, conversation_id}
          case 'error':   cb.onError(new Error(event.message)); return;
        }
      }
    }
  } catch (err) {
    if ((err as Error).name !== 'AbortError') cb.onError(err as Error);
  }
}
```

```typescript
// hooks/useSSE.ts —— 供组件订阅流式状态的便捷 hook
import { useChatStore } from '@/stores/chatStore';

export function useSSE() {
  const isStreaming = useChatStore((s) => s.isStreaming);
  const streamingContent = useChatStore((s) => s.streamingContent);
  const sources = useChatStore((s) => s.sources);
  const abortStream = useChatStore((s) => s.abortStream);
  return { isStreaming, streamingContent, sources, abortStream };
}
```

**渲染链路**：

```
后端 SSE 字节流
  → reader.read() 分片
  → buffer 按 \n 切行（处理跨分片的不完整行）
  → 解析 data: JSON
  → sources → chatStore.sources                  → <SourcePanel> 先渲染来源卡片（先于正文）
  → token   → chatStore.streamingContent += text → <StreamingText> 重渲染（打字机效果）
  → done    → 用累积内容 + message_id 构造完整消息 push → <StreamingText> 卸载，<MessageBubble> 接管
  → error   → 保留已收到的 streamingContent，气泡内提示错误 + 重试
```

### 6.3 文件上传

```typescript
// api/documents.ts（上传部分）
import { client } from './client';

export function upload(
  kbId: number,
  file: File,
  opts: { signal?: AbortSignal; onUploadProgress?: (pct: number) => void } = {}
): Promise<{ document_id: number; status: string }> {
  const form = new FormData();
  form.append('file', file);
  // axios 通过 onUploadProgress 原生支持上传进度；后端返回 202 {document_id, status: "pending"}
  return client
    .post(`/knowledge-bases/${kbId}/documents`, form, {
      signal: opts.signal,
      onUploadProgress: (e) => {
        if (e.total) opts.onUploadProgress?.(Math.round((e.loaded / e.total) * 100));
      },
    })
    .then((res) => res.data);
}
```

```typescript
// hooks/useUpload.ts
import { useEffect, useRef, useState } from 'react';
import { useKBStore } from '@/stores/knowledgeBaseStore';
import * as docApi from '@/api/documents';

interface UploadItem {
  key: string;             // 本地临时 key（拿到后端 document_id 之前用于定位进度项）
  filename: string;
  progress: number;        // 0~100
  status: 'uploading' | 'done' | 'error';
  error?: string;
}

export function useUpload(kbId: number) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const abortMap = useRef(new Map<string, AbortController>());
  const uploadDocument = useKBStore((s) => s.uploadDocument);
  const updateDocumentStatus = useKBStore((s) => s.updateDocumentStatus);

  // 组件卸载时清理：中止所有进行中的上传与轮询
  useEffect(() => {
    const map = abortMap.current;
    return () => {
      map.forEach((c) => c.abort());
      map.clear();
    };
  }, []);

  const patch = (key: string, p: Partial<UploadItem>) =>
    setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...p } : it)));

  const start = (files: FileList | File[]) => {
    Array.from(files).forEach((file) => {
      const key = `up-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const controller = new AbortController();
      abortMap.current.set(key, controller);
      setItems((prev) => [...prev, { key, filename: file.name, progress: 0, status: 'uploading' }]);

      uploadDocument(kbId, file, {
        signal: controller.signal,
        onUploadProgress: (pct) => patch(key, { progress: pct }),
      })
        .then((documentId) => {                  // 202: {document_id, status: "pending"}
          abortMap.current.delete(key);
          patch(key, { status: 'done', progress: 100 });
          pollDocumentStatus(documentId, controller);   // 复用同一 controller，卸载时可中止
        })
        .catch((err: unknown) => {
          abortMap.current.delete(key);
          if (controller.signal.aborted) return;        // 主动取消 / 卸载，不展示错误
          patch(key, { status: 'error', error: (err as Error).message || '上传失败' });
        });
    });
  };

  const cancel = (key: string) => {
    abortMap.current.get(key)?.abort();
    abortMap.current.delete(key);
    setItems((prev) => prev.filter((it) => it.key !== key));
  };

  // 轮询文档处理状态：间隔 2s，直到 ready / failed，超时 5 分钟
  const pollDocumentStatus = async (docId: number, signal: AbortSignal) => {
    const deadline = Date.now() + 5 * 60 * 1000;
    while (!signal.aborted && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2000));
      if (signal.aborted) return;
      const doc = await docApi.get(docId).catch(() => null);
      if (!doc) continue;
      updateDocumentStatus(docId, doc.status);
      if (doc.status === 'ready' || doc.status === 'failed') return;   // 终态，停止轮询
    }
  };

  return { items, start, cancel };
}
```

**UploadZone 交互**：
- `onDragOver` 阻止默认行为 + 高亮边框；`onDrop` 取 `e.dataTransfer.files` 调 `start()`。
- 文件类型白名单：`.pdf .docx .md .txt`；单文件上限 **50MB**，前端先校验，超限直接 toast 拒绝（后端对超限返回 413 `FILE_TOO_LARGE`）。
- 点击区域触发隐藏 `<input type="file" multiple>`。

### 6.4 Markdown 渲染

```bash
pnpm add react-markdown@^8.0.0 remark-gfm@^3.0.1 react-syntax-highlighter
pnpm add -D @types/react-syntax-highlighter
```

> react-markdown 固定 `^8.0.0`：v9 移除了 `components.text`，不要依赖 text 渲染器拦截纯文本；配套 remark-gfm 用 v3（v4 仅兼容 react-markdown v9+）。
> 引用角标方案：预处理阶段把正文里的 `[1]` 改写为 markdown 链接 `[[1]](#citation-1)`，再在 `a` 组件里识别 `#citation-n` 渲染为可点击角标。

```tsx
// components/chat/MarkdownRenderer.tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { CitationButton } from './CitationButton';

// [1] [2] → [[1]](#citation-1)，借用 markdown 链接让引用可点击
const withCitationLinks = (content: string) =>
  content.replace(/\[(\d+)\]/g, '[[$1]](#citation-$1)');

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }) {
          const match = /language-(\w+)/.exec(className ?? '');
          const text = String(children).replace(/\n$/, '');
          return match ? (
            <SyntaxHighlighter language={match[1]} style={oneDark} PreTag="div" {...props}>
              {text}
            </SyntaxHighlighter>
          ) : (
            <code className="rounded bg-gray-100 px-1 py-0.5 text-sm" {...props}>{children}</code>
          );
        },
        a: ({ href, children }) => {
          const m = /^#citation-(\d+)$/.exec(href ?? '');
          if (m) return <CitationButton index={Number(m[1]) - 1} />;   // 引用角标
          return (
            <a href={href} target="_blank" rel="noreferrer" className="text-blue-600 underline">
              {children}
            </a>
          );
        },
      }}
    >
      {withCitationLinks(content)}
    </ReactMarkdown>
  );
}
```

```tsx
// components/chat/CitationButton.tsx —— 引用角标，点击滚动到对应 SourceCard 并高亮
import { useChatStore } from '@/stores/chatStore';
import { scrollToSource } from '@/utils/scroll';

export function CitationButton({ index }: { index: number }) {
  const sources = useChatStore((s) => s.sources);
  return (
    <button
      className="mx-0.5 rounded bg-blue-100 px-1 text-xs text-blue-700 align-super"
      onClick={() => scrollToSource(index)}
      title={sources[index]?.filename}
    >
      [{index + 1}]
    </button>
  );
}
```

```typescript
// utils/scroll.ts —— 滚动到来源卡片并短暂高亮
export function scrollToSource(index: number) {
  const el = document.getElementById(`source-card-${index}`);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  el.classList.add('ring-2', 'ring-blue-500');
  setTimeout(() => el.classList.remove('ring-2', 'ring-blue-500'), 2000);
}
```

配套约定：`SourcePanel` 渲染每张来源卡片时携带 `id={`source-card-${index}`}`（index 从 0 开始，与 `sources` 数组顺序一致），`scrollToSource` 依此定位。

---

## 7. 页面线框图（ASCII art）

### 7.1 Login 页

```
┌────────────────────────────────────────────────────────┐
│                                                        │
│                                                        │
│              ┌──────────────────────────┐              │
│              │         MaxKB Logo       │              │
│              │                          │              │
│              │  邮箱                     │              │
│              │  ┌──────────────────┐    │              │
│              │  │ you@example.com  │    │              │
│              │  └──────────────────┘    │              │
│              │  密码                     │              │
│              │  ┌──────────────────┐    │              │
│              │  │ ••••••••         │    │              │
│              │  └──────────────────┘    │              │
│              │                          │              │
│              │  ┌──────────────────┐    │              │
│              │  │      登  录       │    │              │
│              │  └──────────────────┘    │              │
│              │                          │              │
│              │   没有账号？去注册 →      │              │
│              └──────────────────────────┘              │
│                                                        │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### 7.2 Dashboard（知识库列表）

```
┌────────┬───────────────────────────────────────────────────┐
│ Sidebar│  知识库                          [+ 新建知识库]     │
│        ├───────────────────────────────────────────────────┤
│ ▸ 概览  │  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│ ▸ 对话  │  │ 📚 产品手册  │  │ 📚 客服 FAQ  │  │ ＋ 新建   │ │
│ ▸ 设置  │  │             │  │             │  │          │ │
│        │  │ 产品使用与FAQ│  │ 答疑与FAQ    │  │          │ │
│        │  │ 更新于 08-04 │  │ 更新于 08-03 │  │          │ │
│ ────── │  └─────────────┘  └─────────────┘  └──────────┘ │
│ 👤 用户 │                                                  │
└────────┴───────────────────────────────────────────────────┘
```

### 7.3 Documents 页（上传 + 列表 + 分段预览）

```
┌────────┬───────────────────────────────────────────────────┐
│ Sidebar│  产品手册 / 文档管理                                │
│        ├───────────────────────────────────────────────────┤
│        │  ┌─────────────────────────────────────────────┐  │
│        │  │   ⬆ 拖拽文件到此处，或点击上传                 │  │
│        │  │     支持 pdf / docx / md / txt，≤ 50MB       │  │
│        │  └─────────────────────────────────────────────┘  │
│        │  上传中：产品白皮书.pdf  ████████░░ 82%   [取消]   │
│        ├───────────────────────────────────────────────────┤
│        │  文档列表                                          │
│        │  ┌─────────────────────────────────────────────┐  │
│        │  │ ● ready      产品手册v2.pdf  2.1MB  48段     │  │
│        │  │                    [预览分段] [重试] [删除]   │  │
│        │  │ ◐ processing 安装指南.docx   0.8MB  --      │  │
│        │  │ ✕ failed     旧版手册.pdf    1.2MB  解析超时  │  │
│        │  └─────────────────────────────────────────────┘  │
│        ├───────────────────────────────────────────────────┤
│        │  分段预览（产品手册v2.pdf）            [×]          │
│        │  #1  MaxKB 是一款开源的知识库问答系统…              │
│        │  #2  支持 PDF、Word、Markdown 等格式…              │
│        │  #3  安装要求：Docker 20.10+ …                    │
└────────┴───────────────────────────────────────────────────┘
```

### 7.4 Chat 页（会话列表 + 聊天区 + 来源面板）

```
┌────────┬──────────────┬──────────────────────────┬─────────────┐
│ Sidebar│ 会话列表      │  聊天区                   │ 来源面板     │
│        ├──────────────┤                          ├─────────────┤
│ ▸ 概览  │ KB: 产品手册 ▾│  ┌─ user ────────────┐  │ 检索到 3 条  │
│ ▸ 对话  │ [+ 新对话]    │  │ 如何部署 MaxKB？    │  │ ┌─────────┐ │
│ ▸ 设置  │ ● 部署咨询    │  └───────────────────┘  │ │[1] 安装指南│ │
│        │ ○ 功能对比    │  ┌─ assistant ─────────┐ │ │ .docx    │ │
│        │ ○ API 接入    │  │ 您可以使用 Docker    │ │ │ 相似度0.87│ │
│        │              │  │ 快速部署 [1][2]：     │ │ │ "Docker  │ │
│        │              │  │ ```bash             │ │ │  部署步骤…"│ │
│        │              │  │ docker compose up -d│ │ │ └─────────┘ │
│        │              │  │ ```                 │ │ │ ┌─────────┐ │
│        │              │  └───────────────────┘  │ │[2] 产品手册│ │
│        │              │  ▍(流式输出中…)           │ │ │ …       │ │
│        │              ├──────────────────────────┤ │ └─────────┘ │
│        │              │ [输入消息…        ] [发送]│ │             │
└────────┴──────────────┴──────────────────────────┴─────────────┘
  64px      240px                 flex-1                 320px
```

---

## 8. 响应式断点

Tailwind 默认断点：`sm:640px` `md:768px` `lg:1024px` `xl:1280px`。本项目主要使用 `md` 与 `lg`。

| 断点 | 范围 | 布局策略 |
|------|------|----------|
| Mobile | < 768px | Sidebar 收起为底部 Tab 或汉堡菜单抽屉；Chat 页隐藏会话列表与来源面板，会话列表改为全屏抽屉（点击按钮展开）；来源卡片内联显示在消息气泡下方；表单纵向堆叠 |
| Tablet | 768–1024px | Sidebar 收起为 64px 图标栏（hover 展开）；Chat 页显示会话列表，来源面板隐藏（引用角标点击后以 Modal 展示来源）；Dashboard 卡片 2 列 |
| Desktop | > 1024px | 完整三栏：Sidebar 240px + 主内容 flex-1 + Chat 来源面板 320px；Dashboard 卡片 3~4 列 |

**实现要点**：

```tsx
// ChatPage 响应式示例
<div className="flex h-full">
  {/* 会话列表：移动端为抽屉，md 以上常驻 */}
  <aside className={cn(
    'fixed inset-y-0 z-40 w-64 transform transition-transform md:static md:translate-x-0',
    drawerOpen ? 'translate-x-0' : '-translate-x-full'
  )}>
    <ConversationList />
  </aside>

  <main className="flex-1"><ChatWindow /></main>

  {/* 来源面板：仅 lg 以上显示 */}
  <aside className="hidden w-80 border-l lg:block">
    <SourcePanel />
  </aside>
</div>
```

断点判断统一用 Tailwind 类（`hidden lg:block`），**禁止**在 JS 里 `window.innerWidth` 手写媒体查询；确需 JS 判断时使用 `useMediaQuery('(min-width: 1024px)')` 统一封装。

---

## 9. 错误处理

### 9.1 统一策略

所有错误经 `api/client.ts` 响应拦截器归一化为 `ApiError`，由调用方（store/page）捕获后通过全局 toast 展示：

```typescript
// utils/errors.ts
export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

// api/client.ts 响应拦截器中抛出前统一包装
function toApiError(err: AxiosError): ApiError {
  const data = err.response?.data as { message?: string; code?: string } | undefined;
  return new ApiError(
    err.response?.status ?? 0,
    data?.message ?? err.message,
    data?.code
  );
}
```

### 9.2 分状态码处理表

| 状态码 | 处理方式 | 用户可见反馈 |
|--------|----------|--------------|
| 网络错误（无 response） | 不重试，toast | toast：「网络连接失败，请检查网络」 |
| 400 | toast 展示后端 `message`（表单校验错误定位到字段） | 表单字段下方红字 |
| 401 | 拦截器自动 refresh → 重放；refresh 失败则 logout + 跳转 `/login` | 无感（成功时）/ 跳登录页 |
| 403 | toast | 「没有权限执行该操作」 |
| 404 | 页面级展示 Empty 组件 | 「资源不存在或已被删除」 |
| 413 | toast | 「文件超过 50MB 限制」 |
| 429 | toast + 禁用提交按钮 5s | 「请求过于频繁，请稍后再试」 |
| 500 | toast + 附「报告问题」按钮（复制 requestId 到剪贴板） | 「服务器开小差了」+ 报告按钮 |
| SSE 流中断 | 保留已收到的 streamingContent，标灰显示 + 「重试」按钮 | 气泡内 inline 提示 |

### 9.3 Toast 组件约定

- 全局单例，挂载在 `main.tsx` 根部：`<Toaster position="top-center" />`。
- 通过 `toast.error(msg)` / `toast.success(msg)` 调用（基于 `sonner` 或自研轻量实现）。
- 自动 4s 消失；error 类型可手动关闭；同一消息 2s 内去重。

---

## 10. 构建与部署

### 10.1 构建

```bash
pnpm build         # tsc -b && vite build → dist/ 纯静态文件
pnpm preview       # 本地预览生产构建
```

- 产物：`dist/index.html` + `dist/assets/*.{js,css}`（文件名含 content hash，可永久缓存）。
- TypeScript 严格模式（`strict: true`），构建前 `tsc -b` 类型检查失败即终止。
- 代码分割：React Router 路由级 `lazy()` + `Suspense`，每个 page 独立 chunk；`react-syntax-highlighter` 动态 import（仅 Chat 页用到）。

### 10.2 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `VITE_API_BASE_URL` | 后端 API 地址；生产留空走同源 `/api/v1` 由 Nginx 代理 | 开发：`http://localhost:8000/api/v1`；生产：`/api/v1` |

文件：`.env.development` / `.env.production`，仅 `VITE_` 前缀变量会注入前端（Vite 安全约定，**禁止**在此放任何密钥）。

### 10.3 Nginx 配置

```nginx
server {
    listen 80;
    server_name maxkb.example.com;

    root /usr/share/nginx/html;          # dist/ 部署目录
    index index.html;

    # 静态资源：hash 文件名，永久缓存
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # SPA 路由兜底：所有非文件请求返回 index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 反向代理（含 SSE：关闭缓冲，否则流式输出会被攒包）
    location /api/v1/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # ---- SSE 关键配置 ----
        proxy_buffering off;             # 禁用响应缓冲，逐字节转发
        proxy_cache off;
        proxy_read_timeout 300s;         # 流式回答可能持续数分钟
        chunked_transfer_encoding on;
    }
}
```

### 10.4 开发环境代理（vite.config.ts）

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      '/api/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE 开发调试时可关闭压缩，避免缓冲干扰
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          markdown: ['react-markdown', 'remark-gfm'],
        },
      },
    },
  },
});
```

### 10.5 部署检查清单

- [ ] `VITE_API_BASE_URL` 为空或 `/api/v1`（走同源代理，避免 CORS）
- [ ] Nginx `proxy_buffering off` 已生效（`curl -N` 验证流式逐字输出）
- [ ] refresh_token 仅存内存/localStorage，refresh / logout 均以 JSON body 发送（不依赖 cookie）
- [ ] `dist/assets/` 命中强缓存（DevTools Network 验证 `200 (from disk cache)`）
- [ ] 路由深链刷新不 404（`try_files` 兜底验证）

---

## 附录：依赖清单（package.json 核心）

```json
{
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.26.0",
    "zustand": "^4.5.0",
    "axios": "^1.7.0",
    "react-markdown": "^8.0.0",
    "remark-gfm": "^3.0.1",
    "react-syntax-highlighter": "^15.5.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.5.0",
    "sonner": "^1.5.0"
  },
  "devDependencies": {
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "@vitejs/plugin-react": "^4.3.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "@types/node": "^20.14.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@types/react-syntax-highlighter": "^15.5.0"
  }
}
```
