<!-- Phase: Phase 3.2 - UI/UX Design -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Page: 登录页面 -->

# 登录页面（Login Page）

## 页面结构

```
LoginPage
├── Background (全屏, 渐变背景)
├── LoginCard (居中, max-width: 400px)
│   ├── Logo (居中, 48px)
│   ├── Title: "智能招聘助手"
│   ├── Subtitle: "企业级 AI 简历推荐系统"
│   ├── Divider
│   ├── UsernameInput
│   │   ├── Label: "用户名"
│   │   ├── Input (placeholder: "请输入用户名")
│   │   └── ValidationMsg (条件渲染)
│   ├── PasswordInput
│   │   ├── Label: "密码"
│   │   ├── Input (type=password, placeholder: "请输入密码")
│   │   ├── ShowHideToggle
│   │   └── ValidationMsg (条件渲染)
│   ├── ErrorBanner (条件渲染: 认证失败)
│   ├── LoginButton (primary, full-width, "登录")
│   └── Footer: "V1.0 - 企业内部使用"
└── Copyright (底部居中)
```

## 交互状态

| 状态 | 表现 |
|------|------|
| 初始 | 表单为空，按钮 disabled |
| 输入中 | 实时校验，非法时输入框红色边框 + 提示 |
| 可提交 | 表单有效，按钮 enabled |
| 提交中 | 按钮 disabled + loading spinner，表单不可编辑 |
| 成功 | 页面淡出 -> 跳转到主聊天页面 |
| 失败 | ErrorBanner fadeIn（红色）+ 输入框 shake 动画 |
| 锁定 | 3次失败 -> 表单禁用 + 倒计时提示 |

## 响应式

| 断点 | 表现 |
|------|------|
| >= 768px | LoginCard 居中, max-width 400px |
| < 768px | LoginCard 全宽, padding 16px, 无圆角 |
