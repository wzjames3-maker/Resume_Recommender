<!-- Phase: Phase 3.2 - UI/UX Design -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Component: 组件清单 -->

# 组件清单（Component Inventory）

## 通用组件

### Button
| 变体 | 样式 | 使用场景 |
|------|------|----------|
| primary | 蓝色背景, 白色文字 | 主要操作（发送、登录、确认） |
| secondary | 灰色边框, 灰色文字 | 次要操作（取消、返回） |
| danger | 红色背景, 白色文字 | 危险操作（删除） |
| ghost | 透明背景, 蓝色文字 | 文字链接式操作 |
| icon | 无背景, 图标 | 图标按钮（关闭、菜单） |

| 状态 | 表现 |
|------|------|
| default | 正常显示 |
| hover | 背景色加深 |
| disabled | 50% 透明度, cursor: not-allowed |
| loading | 显示 spinner, 文字隐藏 |

---

### Input
| 变体 | 样式 | 使用场景 |
|------|------|----------|
| text | 单行文本输入 | 用户名、搜索框 |
| password | 密码输入 + 显示/隐藏切换 | 登录密码 |
| textarea | 多行文本输入 | 聊天输入框 |

| 状态 | 表现 |
|------|------|
| default | 灰色边框 |
| focus | 蓝色边框 + 外发光 |
| error | 红色边框 + 错误提示 |
| disabled | 灰色背景, 不可编辑 |

---

### Tag
| 变体 | 样式 | 使用场景 |
|------|------|----------|
| filter | 蓝色背景, 可关闭 | 当前筛选条件（#Java #杭州） |
| skill-matched | 绿色背景, 绿色文字 | 匹配的技能 |
| skill-missing | 灰色背景, 灰色文字, 虚线边框 | 缺失的技能 |
| role | 灰色背景 | 用户角色标签（admin/hr） |

---

### ScoreBar
| 属性 | 说明 |
|------|------|
| value | 0-100 数值 |
| color | >= 80 绿色, 60-79 黄色, < 60 红色 |
| height | 8px |
| radius | 4px |
| 显示 | 右侧显示数值 |

---

## 聊天组件

### UserMessage
```
UserMessage
├── Avatar (用户头像, 右侧)
├── Bubble (蓝色背景, 白色文字, 右对齐)
│   └── Content (文本, 支持换行)
└── Timestamp (灰色小字, 右侧)
```

---

### AssistantMessage
```
AssistantMessage
├── Avatar (助手头像, 左侧)
├── Bubble (白色背景, 深色文字, 左对齐)
│   ├── TextContent (普通文本)
│   ├── CandidateCards (条件渲染: 推荐结果)
│   ├── ComparisonTable (条件渲染: 对比结果)
│   ├── CandidateDetail (条件渲染: 详情)
│   └── ErrorContent (条件渲染: 错误提示 + 重试按钮)
└── Timestamp (灰色小字, 左侧)
```

---

### TypingIndicator
```
TypingIndicator
├── Avatar (助手头像)
└── Dots (三个跳动的点, 间隔 0.3s)
```
- 动画: 三个点依次上下跳动
- 持续: 直到收到第一个 Token

---

### CandidateCard
```
CandidateCard (白色卡片, 圆角, 阴影)
├── Header
│   ├── RankBadge (#1, #2, ... 圆形, 蓝色)
│   ├── Name (粗体)
│   ├── CurrentTitle (灰色)
│   └── ScoreBar + ScoreValue
├── Body
│   ├── ReasonList (推荐理由, 前面带绿色勾)
│   ├── SkillTags (匹配技能, 绿色标签)
│   └── MissingSkillTags (缺失技能, 灰色虚线标签)
└── Footer
    ├── DetailButton: "查看详情" (ghost)
    └── CompareCheckbox (条件渲染: 多个结果时)
```

| 状态 | 表现 |
|------|------|
| default | 白色卡片, 轻微阴影 |
| hover | 阴影加深, 轻微上移 2px |
| selected (对比) | 蓝色边框 |

---

### FilterTags
```
FilterTags (横向滚动区域)
├── Label: "筛选条件:"
├── Tag (each, 可关闭)
│   ├── Text (条件名称)
│   └── CloseIcon (点击移除该条件)
└── ClearAll: "清除全部"
```

---

### WelcomeMessage
```
WelcomeMessage (居中)
├── Logo (大尺寸)
├── Title: "智能招聘助手"
├── Subtitle: "告诉我您的招聘需求，我来帮您找人"
├── Description: "我可以帮您搜索候选人、查看简历、对比候选人等"
└── SuggestionChips (横向排列, 可点击)
    ├── Chip: "找5年Java工程师，杭州"
    ├── Chip: "推荐几个算法工程师"
    └── Chip: "上传简历"
```

---

## 侧边栏组件

### ConversationItem
```
ConversationItem (可点击)
├── Title (对话标题, 单行截断)
├── Preview (最后一条消息预览, 灰色, 单行截断)
├── Time (相对时间, 如"3分钟前")
└── DeleteButton (hover 时显示, 红色)
```

| 状态 | 表现 |
|------|------|
| default | 白色背景 |
| hover | 浅灰色背景 |
| active (当前对话) | 蓝色左边框 + 浅蓝色背景 |

---

## 弹窗组件

### CandidateDetailModal
```
CandidateDetailModal (Overlay)
├── Modal (白色卡片, 居中, max-width: 640px, max-height: 80vh)
│   ├── Header
│   │   ├── Name + ScoreBadge
│   │   └── CloseButton (右上角 X)
│   ├── Body (可滚动)
│   │   ├── Section: 基本信息
│   │   ├── Section: 教育经历 (Timeline 布局)
│   │   ├── Section: 工作经历 (Timeline 布局)
│   │   ├── Section: 项目经历 (卡片布局)
│   │   ├── Section: 技能列表 (标签布局)
│   │   └── Section: 匹配详情 (评分拆解)
│   └── Footer
│       └── CloseButton
```

| 状态 | 表现 |
|------|------|
| opening | fadeIn + scale 0.95 -> 1 |
| open | 正常显示 |
| closing | fadeOut + scale 1 -> 0.95 |

---

### UploadModal
```
UploadModal (Overlay)
├── Modal (白色卡片, max-width: 480px)
│   ├── Title: "上传简历"
│   ├── DropZone (拖拽区域, 虚线边框)
│   │   ├── Icon (上传图标)
│   │   ├── Text: "拖拽文件到此处或点击选择"
│   │   ├── FormatHint: "支持 PDF / DOCX / JSON"
│   │   └── FileInput (隐藏, 点击触发)
│   ├── FilePreview (条件渲染: 已选文件)
│   │   ├── FileName
│   │   ├── FileSize
│   │   └── RemoveButton
│   ├── ProgressBar (条件渲染: 上传中)
│   ├── StatusMessage (条件渲染: 结果)
│   │   ├── Success: 绿色 + 解析摘要
│   │   └── Error: 红色 + 错误信息
│   └── Actions
│       ├── CancelButton (secondary)
│       └── UploadButton (primary, disabled until file selected)
```
