<!-- Phase: Phase 3.2 - UI/UX Design -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Page: 主聊天页面 -->

# 主聊天页面（Chat Page）

## 页面结构

```
ChatPage
├── Sidebar (左侧, 280px, 可折叠)
│   ├── Logo + 系统名称
│   ├── NewChatButton (新建对话)
│   ├── ConversationList (历史对话列表)
│   │   ├── ConversationItem (each: 标题 + 时间 + 删除按钮)
│   │   └── ... (滚动列表)
│   ├── Divider
│   ├── UploadButton (上传简历)
│   └── UserInfo (用户名 + 角色标签 + 退出按钮)
│
└── MainArea (右侧, 填充剩余宽度)
    ├── ChatHeader (当前对话标题 + 操作按钮)
    │   ├── Title (自动生成的对话标题)
    │   └── Actions (清除对话 / 导出)
    │
    ├── MessageList (消息列表, 可滚动)
    │   ├── WelcomeMessage (条件渲染: 无消息时显示)
    │   │   ├── Logo
    │   │   ├── Title: "智能招聘助手"
    │   │   ├── Subtitle: "告诉我您的招聘需求，我来帮您找人"
    │   │   └── SuggestionChips (示例查询)
    │   │       ├── "找5年Java工程师，杭州"
    │   │       ├── "推荐几个算法工程师"
    │   │       └── "上传简历"
    │   │
    │   ├── UserMessage (右侧气泡, 蓝色背景)
    │   │   └── Content (文本)
    │   │
    │   └── AssistantMessage (左侧气泡, 白色背景)
    │       ├── TextContent (普通文本回复)
    │       └── CandidateCards (条件渲染: 推荐结果)
    │           ├── FilterTags (当前筛选条件标签)
    │           │   ├── Tag: "Java" (可点击移除)
    │           │   ├── Tag: "杭州"
    │           │   ├── Tag: ">=5年"
    │           │   └── ...
    │           ├── CandidateCard (each)
    │           │   ├── RankBadge (#1, #2, ...)
    │           │   ├── Name + CurrentTitle
    │           │   ├── ScoreBar (0-100, 颜色渐变)
    │           │   ├── ScoreValue (数值)
    │           │   ├── ReasonList (推荐理由, 2-3条)
    │           │   ├── SkillTags (匹配技能, 绿色)
    │           │   ├── MissingSkillTags (缺失技能, 灰色虚线)
    │           │   └── DetailButton: "查看详情"
    │           ├── SummaryText (结果摘要: "共找到28位候选人，为您推荐Top 10")
    │           └── CompareButton: "对比前两个" (条件渲染: >=2条结果)
    │
    └── InputArea (底部固定)
        ├── InputBox (文本输入框, 多行, placeholder: "描述您的招聘需求...")
        ├── SendButton (发送按钮)
        └── InputHints (底部提示: "Shift+Enter 换行, Enter 发送")
```

## 交互状态

| 状态 | 表现 |
|------|------|
| 初始（无消息） | 显示 WelcomeMessage + SuggestionChips |
| 用户输入中 | 输入框自适应高度，SendButton 可用 |
| 等待响应 | 输入框 disabled，助手区域显示 typing indicator（三个跳动的点） |
| Streaming 输出 | 文本逐字显示，候选人卡片渐入 |
| 推荐成功 | 候选人卡片列表 + 筛选条件标签 |
| 空结果 | "未找到符合条件的候选人，请尝试调整搜索条件" |
| 错误 | 红色错误提示 + "重试"按钮 |
| 加载更多 | "正在为您检索更多..." |

## 候选人详情弹窗（Candidate Detail Modal）

```
CandidateDetailModal (Overlay)
├── Header
│   ├── Name + Avatar
│   ├── CloseButton
│   └── ScoreBadge
├── Body (可滚动)
│   ├── BasicInfo Section
│   │   ├── Gender, Age, City
│   │   ├── Phone (脱敏: 138****1234)
│   │   └── Email (脱敏: zhang***@gmail.com)
│   ├── Education Section
│   │   └── EducationItem (each: 学校, 学历, 专业, 时间)
│   ├── Experience Section
│   │   └── ExperienceItem (each: 公司, 职位, 行业, 时间, 是否外包)
│   ├── Project Section
│   │   └── ProjectItem (each: 项目名, 角色, 技术栈, 描述, 时间)
│   ├── Skills Section
│   │   └── SkillItem (each: 技能名, 熟练程度, 年限, 分类)
│   └── MatchDetail Section
│       ├── ScoreBreakdown (各维度评分)
│       ├── MatchedSkills (匹配技能)
│       └── MissingSkills (缺失技能)
└── Footer
    └── CloseButton
```

## 响应式

| 断点 | 表现 |
|------|------|
| >= 1024px | Sidebar 280px 固定显示 |
| 768px - 1023px | Sidebar 可折叠，默认折叠 |
| < 768px | Sidebar 默认隐藏，点击汉堡菜单展开 |
