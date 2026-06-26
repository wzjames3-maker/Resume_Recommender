# T-034: Streamlit 登录页 + 聊天主界面

## 基本信息
- **对应 Spec**: frontend 00-overview
- **对应 AC**: AC-001 ~ AC-006
- **依赖任务**: T-030（Chat API SSE）, T-032（Login API）
- **预计工时**: 2 天
- **优先级**: P0

## 输入
- T-030 产出的 `/api/v1/chat` SSE 端点
- T-032 产出的 `/api/v1/auth/login` 端点 + JWT 认证机制
- Frontend Spec `00-overview.md` 中的页面定义和交互规范

## 输出
- `src/frontend/app.py` — Streamlit 主入口
- `src/frontend/pages/login.py` — 登录页
- `src/frontend/pages/chat.py` — 聊天主界面
- `src/frontend/utils/api.py` — API 调用封装（含 SSE 客户端）
- `src/frontend/utils/session.py` — 会话状态管理
- Streamlit 可通过 `streamlit run src/frontend/app.py` 启动

## 实现要求

### 登录页
1. 用户名/密码输入框 + 登录按钮
2. 登录成功后将 JWT 存入 `st.session_state`
3. 登录失败显示错误提示（不暴露具体原因）
4. 已登录用户自动跳转到聊天页

### 聊天主界面
1. 使用 `st.chat_message` 渲染历史消息
2. 使用 `st.chat_input` 接收用户输入
3. 发送消息后调用 `/api/v1/chat` SSE 端点
4. 流式接收 token 并逐字渲染（实时更新 `st.chat_message`）
5. 流结束后展示候选人摘要卡片（可简化为文本列表，T-035 做完整卡片）

### SSE 客户端
1. 使用 `httpx` + `stream=True` 或 `sseclient-py` 接收 SSE
2. 解析 `data: {JSON}\n\n` 格式
3. 处理 `token`、`sources`、`done` 三种 event type
4. 连接异常时显示错误提示

### 会话管理
1. 使用 `st.session_state` 存储：
   - `access_token` — JWT
   - `user_info` — 用户信息
   - `conversation_id` — 当前对话 ID
   - `messages` — 当前对话消息列表
2. 页面切换时保持状态
3. Token 过期时自动跳转登录页

## 验收检查点

### 前置确认
- [ ] T-030 已完成并通过验收（Chat API 可用）
- [ ] T-032 已完成并通过验收（Login API 可用）
- [ ] Streamlit 依赖已安装
- [ ] `streamlit run` 可正常启动

### AC 验收
- [ ] **AC-001**: 用户输入搜索请求，聊天界面实时流式输出回复
- [ ] **AC-002**: 回复结束后显示候选人摘要信息
- [ ] **AC-003**: 上传简历入口可见（可先用按钮占位，T-035 实现完整功能）
- [ ] **AC-004**: 错误密码登录显示失败提示
- [ ] **AC-005**: 登录成功后进入聊天主界面，token 正确存储
- [ ] **AC-006**: 刷新页面后登录状态保持（session_state）

### 代码质量
- [ ] API 调用封装在 `utils/api.py`，与页面逻辑解耦
- [ ] SSE 客户端支持中断（用户发送新消息时取消上一个流）
- [ ] 无硬编码的 API 地址，使用环境变量或配置文件
- [ ] Streamlit 页面无未捕获异常导致白屏

### Spec 一致性
- [ ] 页面布局与 `00-overview.md` 设计一致
- [ ] 交互流程符合 Spec 描述
- [ ] 错误提示文案与 Spec 一致

### 通过判定
- [ ] 所有 AC 验收项通过
- [ ] 手动操作全流程：登录 → 聊天 → 流式输出 → 看到候选人
- [ ] 无 Streamlit 运行时报错
