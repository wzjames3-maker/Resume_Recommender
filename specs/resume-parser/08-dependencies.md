<!-- Module: resume-parser -->
<!-- Spec Layer: 08 - Dependencies -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 模块依赖关系：Resume Parser

## 1. 依赖总览

Resume Parser 是系统的**基础数据入口模块**，在依赖链中处于最上游位置。

```
                    ┌──────────────┐
                    │   api-layer  │ (HTTP 调用方)
                    └──────┬───────┘
                           │ 调用
                           ▼
                    ┌──────────────┐
                    │resume-parser │ ◄── 本模块
                    └──────┬───────┘
                           │ 输出 ResumeSchema
                ┌──────────┼──────────┐
                ▼                     ▼
         ┌──────────────┐     ┌──────────────┐
         │ resume-store │     │ vector-index │
         └──────────────┘     └──────────────┘
```

---

## 2. 前置依赖（本模块依赖的模块）

**本模块无前置模块依赖** — Resume Parser 是系统最基础的模块，不依赖其他业务模块。

### 2.1 外部服务依赖

| 依赖 | 类型 | 必选 | 降级策略 | 说明 |
|------|------|------|----------|------|
| DeepSeek LLM API | 外部 API | ✅ | 切换到 OpenAI API | LLM 结构化提取（REQ-005） |
| DeepSeek-OCR API | 外部 API | ✅（图片/扫描件） | 返回错误，建议转换格式 | OCR 文字识别（REQ-003） |
| OpenAI API | 外部 API | ❌（备选） | - | DeepSeek 不可用时的降级方案 |

### 2.2 基础设施依赖

| 依赖 | 类型 | 必选 | 说明 |
|------|------|------|------|
| Python 3.11+ | 运行时 | ✅ | Python 解释器 |
| Docker | 部署 | ✅ | 容器化运行环境 |
| 环境变量 | 配置 | ✅ | API Key、加密密钥等 |

### 2.3 数据文件依赖

| 依赖 | 路径 | 格式 | 必选 | 说明 |
|------|------|------|------|------|
| Skill 同义词词典 | `config/skill_synonyms.json` | JSON | ✅ | Skill 标准化映射（RULE-006） |

---

## 3. 后置依赖（依赖本模块的模块）

### 3.1 resume-store

| 维度 | 说明 |
|------|------|
| **依赖方向** | resume-store ← resume-parser |
| **数据流** | `ParseResult` → resume-store |
| **接口** | resume-store 接收 `ResumeSchema` 写入 MongoDB |
| **职责边界** | resume-parser 负责解析和结构化；resume-store 负责持久化、生成 resume_id、PII 加密存储 |
| **调用方式** | api-layer 解析完成后，调用 resume-store 的写入接口 |

**传递数据**:
```python
# resume-parser 输出 → resume-store 输入
{
    "resume_data": ResumeSchema,      # 结构化简历数据
    "raw_text": str,                   # 原始文本（用于后续重新解析）
    "status": ParseStatus,             # 解析状态
    "metadata": ResumeMetadata         # 解析元数据
}
```

### 3.2 vector-index

| 维度 | 说明 |
|------|------|
| **依赖方向** | vector-index ← resume-parser |
| **数据流** | 可索引文本 → vector-index |
| **接口** | vector-index 接收 resume_id + 文本，生成 Embedding 写入 Milvus |
| **职责边界** | resume-parser 提供结构化文本；vector-index 负责 Embedding 生成和向量存储 |
| **调用方式** | resume-store 写入成功后，调用 vector-index 的索引接口 |

**传递数据**:
```python
# resume-store 入库后 → vector-index 输入
{
    "resume_id": str,                  # 由 resume-store 生成
    "text_for_embedding": str,         # 可索引的简历文本（摘要+技能+经历）
    "metadata": {
        "city": str,
        "education": str,
        "experience_years": int,
        "skills": list[str]
    }
}
```

---

## 4. 调用方依赖

### 4.1 api-layer（HTTP 接口层）

| 维度 | 说明 |
|------|------|
| **依赖方向** | api-layer → resume-parser |
| **接口** | `parse_resume(file: UploadFile) -> ParseResult` |
| **职责** | api-layer 负责文件大小校验、类型白名单、HTTP 错误码映射 |
| **错误映射** | api-layer 将 ParseStatus 映射为 HTTP 状态码（见下表） |

**HTTP 状态码映射**:

| ParseStatus | HTTP Status | 说明 |
|-------------|-------------|------|
| SUCCESS | 200 | 解析成功 |
| PARTIAL | 200 | 部分成功（返回警告） |
| FAILED | 422 | 解析失败 |
| - (文件过大) | 413 | 文件超过 20MB |
| - (格式不支持) | 415 | 不支持的文件格式 |

---

## 5. 模块依赖图（全景）

```
┌─────────────────────────────────────────────────────────────────┐
│                        外部服务                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐        │
│  │ DeepSeek LLM  │  │ DeepSeek-OCR  │  │ OpenAI (备选)  │        │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘        │
│          │                  │                  │                │
└──────────┼──────────────────┼──────────────────┼────────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
    ┌─────────────────────────────────────────────────┐
    │              resume-parser (本模块)               │
    │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐│
    │  │ PDF     │ │ DOCX    │ │ OCR     │ │ JSON   ││
    │  │ Extract │ │ Extract │ │ Extract │ │ Import ││
    │  └────┬────┘ └────┬────┘ └────┬────┘ └───┬────┘│
    │       └────────────┴──────────┴───────────┘     │
    │                      │                          │
    │              ┌───────▼───────┐                  │
    │              │ LLM 结构化提取  │                  │
    │              └───────┬───────┘                  │
    │              ┌───────▼───────┐                  │
    │              │ Skill 标准化   │                  │
    │              └───────┬───────┘                  │
    └──────────────────────┼──────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼                               ▼
    ┌──────────────┐                ┌──────────────┐
    │ resume-store │                │ vector-index │
    │  (MongoDB)   │                │  (Milvus)    │
    └──────────────┘                └──────────────┘
```

---

## 6. 依赖版本锁定

所有依赖版本在 `requirements.txt` 或 `pyproject.toml` 中锁定：

```txt
# 简历解析 - 核心依赖
PyPDF2>=3.0,<4.0
pdfplumber>=0.11,<1.0
python-docx>=1.1,<2.0
Pillow>=10.0,<11.0
openai>=1.0,<2.0
pydantic>=2.0,<3.0
httpx>=0.28,<1.0

# 可选
chardet>=5.0,<6.0
```

**版本策略**:
- 使用 `>=` 下限 + `<` 上限（避免大版本升级导致不兼容）
- 定期检查安全更新
- LLM SDK（openai）锁大版本，小版本允许自动升级

---

## 7. 循环依赖检查

| 检查项 | 结果 |
|--------|------|
| resume-parser → resume-store | ❌ 无直接依赖（通过 api-layer 协调） |
| resume-parser → vector-index | ❌ 无直接依赖（通过 api-layer 协调） |
| resume-parser → api-layer | ❌ 不依赖（api-layer 调用 resume-parser） |
| resume-parser → intent-router | ❌ 无依赖 |
| resume-parser → recommendation-engine | ❌ 无依赖 |
| resume-parser → frontend | ❌ 无依赖 |

**结论**: 无循环依赖。resume-parser 处于依赖链最上游，只被下游模块单向调用。

---

## 8. 接口稳定性承诺

| 承诺 | 说明 |
|------|------|
| `parse_resume` 函数签名 | V1 内不变更参数和返回类型 |
| `parse_resume_text` 函数签名 | V1 内不变更参数和返回类型 |
| `standardize_skills` 函数签名 | V1 内不变更参数和返回类型 |
| `ResumeSchema` 结构 | V1 内仅允许新增可选字段，不删除/重命名字段 |
| `ParseStatus` 枚举值 | V1 内不删除已有枚举值，可新增 |

**变更流程**:
1. 修改本模块 Spec（02-data-model.md / 03-api-contract.md）
2. 通知下游模块（resume-store / vector-index / api-layer）负责人
3. 更新版本号
4. 同步更新接口文档
