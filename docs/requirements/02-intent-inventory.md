<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: 02-intent-inventory.md -->
<!-- Date: 2026-06-23 -->

# 02 — 意图清单（Intent Inventory）

## 意图分类总览

| Intent | 分类 | 描述 | 触发 Workflow | 优先级 |
|--------|------|------|---------------|--------|
| ecruitment.search | 招聘 | 初始招聘检索 | Hybrid Search | P0 |
| ecruitment.refine | 招聘 | 对上一次结果进行条件修正 | Filter Last Result | P0 |
| ecruitment.compare | 招聘 | 对比多个候选人 | Candidate Compare | P1 |
| candidate.lookup | 候选人 | 查看某位候选人详情 | Resume Detail | P1 |
| esume.upload | 简历 | 上传新简历入库 | Resume Parser | P0 |
| esume.manage | 简历 | 管理已有简历（删除、重新解析） | Resume Management | P2 |
| knowledge.qa | 知识 | 行业/薪资/岗位知识问答 | Knowledge RAG | P2 |
| nalytics | 分析 | 人才库统计数据查询 | Statistics | P2 |
| chat | 通用 | 闲聊/寒暄/通用对话 | Chat | P3 |
| allback | 兜底 | 无法识别意图 | Recovery | P0 |

## 意图详细定义

### 1. ecruitment.search — 招聘检索

**描述**：HR 发起新的招聘需求，系统进行初始候选人检索。

**典型输入**：
`
找5年Java工程师，杭州，985
推荐几个算法工程师
需要3个有大厂经验的后端
有做过电商的PM吗
`

**Workflow**：
`
Intent Router
    ↓
Slot Extraction
    ↓
Hybrid Retrieval (Dense + Sparse)
    ↓
Metadata Filter
    ↓
LLM Rerank
    ↓
Output Top-N
`

**输出**：候选人列表 + Score + Reason + Skills + Missing

---

### 2. ecruitment.refine — 条件修正

**描述**：HR 在上一次推荐结果基础上，追加/修改/排除条件。

**典型输入**：
`
女生呢
学历高一点
不要外包
年龄小一点
再推荐几个
按经验排序
薪资20k以下的
`

**Workflow**：
`
解析当前 Query 的增量 Slots
    ↓
合并 last_query + last_filters + new_slots
    ↓
在 last_candidates 范围内重新过滤/排序
    ↓
或在全库重新检索（视条件变化幅度）
    ↓
Output Top-N
`

**关键依赖**：Conversation Memory（last_query, last_filters, last_candidates）

---

### 3. ecruitment.compare — 候选人对比

**描述**：HR 要求对比多个候选人。

**典型输入**：
`
对比前两个候选人
张三和李四哪个更合适
这三个人的技能差异是什么
`

**Workflow**：
`
提取目标候选人（从 last_candidates 或 by name）
    ↓
获取各候选人完整简历数据
    ↓
LLM 生成多维度对比分析
    ↓
Output 对比表格
`

---

### 4. candidate.lookup — 候选人详情

**描述**：HR 查看某位候选人的完整信息。

**典型输入**：
`
第一个人是谁
看看张三的简历
他的项目经历详细说说
`

**Workflow**：
`
识别候选人（by name / by position in last_candidates）
    ↓
查询 Resume Store 获取完整数据
    ↓
LLM 生成结构化摘要
    ↓
Output 候选人详情
`

---

### 5. esume.upload — 简历上传

**描述**：HR 或管理员上传新简历到人才库。

**典型输入**：
`
上传这份简历
导入这批简历
`

**Workflow**：
`
接收文件（PDF / DOCX / Image / JSON）
    ↓
Resume Parser 解析
    ↓
写入 Resume Store
    ↓
生成 Embedding → 写入 Milvus
    ↓
更新 Elasticsearch 索引
    ↓
返回入库状态
`

---

### 6. esume.manage — 简历管理

**描述**：对已有简历进行管理操作。

**典型输入**：
`
删除这份简历
重新解析这份简历
更新张三的信息
`

**Workflow**：
`
识别目标简历
    ↓
执行操作（delete / re-parse / update）
    ↓
同步更新 Resume Store + Vector Index + ES
    ↓
返回操作结果
`

---

### 7. knowledge.qa — 知识问答

**描述**：HR 询问行业、薪资、岗位等知识性问题。

**典型输入**：
`
Java工程师薪资范围是多少
P7和P8的职级区别
算法工程师需要什么技能
`

**Workflow**：
`
Knowledge RAG 检索
    ↓
LLM 生成回答
    ↓
Output 知识回答
`

---

### 8. nalytics — 数据分析

**描述**：HR 查询人才库统计数据。

**典型输入**：
`
人才库有多少Java工程师
北京的算法工程师有多少
3年以下经验的有多少人
`

**Workflow**：
`
解析统计维度和条件
    ↓
查询 Resume Store 聚合统计
    ↓
Output 统计结果
`

---

### 9. chat — 闲聊

**描述**：通用对话，无明确业务意图。

**典型输入**：
`
你好
谢谢
今天天气怎么样
`

**Workflow**：
`
LLM 直接回复
    ↓
Output 对话响应
`

---

### 10. allback — 兜底

**描述**：系统无法识别用户意图时的兜底处理。

**典型输入**：
`
asdfghjkl
帮我订个外卖
（语音识别错误的乱码）
`

**Workflow**：
`
意图置信度低于阈值
    ↓
触发 Fallback
    ↓
Output 引导性回复
    例："我是招聘助手，可以帮您搜索候选人、上传简历等，请问有什么需要？"
`

## 意图识别优先级

当多个意图可能匹配时，按以下优先级判断：

`
1. resume.upload        （明确动作，优先识别）
2. resume.manage        （明确动作）
3. recruitment.compare  （包含对比关键词）
4. candidate.lookup     （包含查看详情关键词）
5. recruitment.refine   （有上文且为条件性输入）
6. recruitment.search   （默认招聘意图）
7. analytics            （包含统计关键词）
8. knowledge.qa         （包含知识性关键词）
9. chat                 （通用对话）
10. fallback            （兜底）
`

## Intent Router 设计约束

- 意图识别必须支持上下文（多轮对话），不能仅基于单条消息判断
- ecruitment.refine 依赖 Conversation Memory，必须有上一次 ecruitment.search 的上下文
- allback 必须给出引导性回复，不能静默失败
- 所有意图识别结果必须写入 Audit Log
