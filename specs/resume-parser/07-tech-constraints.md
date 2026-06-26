<!-- Module: resume-parser -->
<!-- Spec Layer: 07 - Technical Constraints -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 技术约束：Resume Parser

## 1. 架构级约束

本模块的技术约束遵循项目级技术选型决策（冻结文件：`docs/tech-decision.md`）。

| 约束 | 决策 | 来源 |
|------|------|------|
| 编程语言 | Python 3.11+ | tech-decision 决策项 1 |
| Web 框架 | FastAPI（内部接口承载） | tech-decision 决策项 2 |
| 数据验证 | Pydantic >= 2.0 | tech-decision 决策项 2 |
| LLM | DeepSeek（主）/ OpenAI（备） | tech-decision 决策项 8 |
| LLM 接口 | OpenAI Compatible API（openai SDK） | tech-decision 决策项 8 |
| 部署 | Docker Compose | tech-decision 决策项 12 |
| 日志 | 结构化 JSON（python-json-logger） | tech-decision 决策项 14 |

---

## 2. Python 依赖清单

### 2.1 必选依赖

| 包名 | 版本要求 | 用途 | 来源 |
|------|----------|------|------|
| `PyPDF2` | >= 3.0 | PDF 文本提取（降级方案） | tech-decision 依赖清单 |
| `pdfplumber` | >= 0.11 | PDF 文本提取（首选） | tech-decision 依赖清单 |
| `python-docx` | >= 1.1 | DOCX 文本提取 | tech-decision 依赖清单 |
| `Pillow` | >= 10.0 | 图片预处理（缩放、格式转换） | tech-decision 依赖清单 |
| `openai` | >= 1.0 | DeepSeek API 调用（OpenAI Compatible） | tech-decision 依赖清单 |
| `pydantic` | >= 2.0 | Schema 定义、数据验证、LLM 输出约束 | tech-decision 决策项 2 |
| `httpx` | >= 0.28 | 异步 HTTP 客户端（OCR API 调用） | tech-decision 依赖清单 |

### 2.2 可选依赖

| 包名 | 版本要求 | 用途 | 说明 |
|------|----------|------|------|
| `chardet` | >= 5.0 | 文本编码检测 | 处理非 UTF-8 编码的 PDF |
| `python-magic` | >= 0.4 | 文件类型检测（magic bytes） | EC-008 文件格式与扩展名不匹配 |

---

## 3. 外部服务依赖

### 3.1 DeepSeek LLM API

| 约束项 | 值 |
|--------|-----|
| 服务 | DeepSeek Chat Completions API |
| 接口协议 | OpenAI Compatible（`/v1/chat/completions`） |
| SDK | `openai` Python SDK |
| 模型 | `deepseek-chat`（默认） |
| Base URL | `https://api.deepseek.com/v1` |
| 认证 | API Key（环境变量 `DEEPSEEK_API_KEY`） |
| 超时 | 60 秒 |
| 最大输出 Token | 4096 |
| Temperature | 0.1（保证输出稳定性） |
| 降级 | DeepSeek 不可用时切换到 OpenAI（`gpt-4o-mini`） |

**使用场景**:
- 简历文本 → 结构化 ResumeSchema（REQ-005）
- 语义切分辅助（REQ-006，可选）

### 3.2 DeepSeek-OCR API

| 约束项 | 值 |
|--------|-----|
| 服务 | DeepSeek-OCR（deepseek-ai/DeepSeek-OCR） |
| 认证 | API Key（环境变量 `DEEPSEEK_OCR_API_KEY`） |
| 输入 | 图片 base64 编码 |
| 输出 | 识别文字文本 |
| 最大图片尺寸 | 4096px（长边） |
| 超时 | 30 秒 |
| 降级 | OCR 不可用时返回错误，建议用户转换格式 |

**使用场景**:
- 图片简历文字识别（REQ-003）
- 扫描件 PDF 图片识别（EC-002）

---

## 4. 禁用技术

| 禁用项 | 原因 | 替代方案 |
|--------|------|----------|
| Tesseract OCR | 中文识别效果差，配置复杂 | DeepSeek-OCR |
| Unstructured.io | 不可控，付费 API | 自研 pdfplumber + python-docx |
| LlamaParse | 付费 API，增加外部依赖 | 自研 |
| Tika | Java 依赖，增加部署复杂度 | Python 原生库 |
| PyMuPDF (fitz) | AGPL 许可证，商业使用受限 | pdfplumber + PyPDF2 |
| .doc 格式支持 | 旧格式，需要 antiword 等系统依赖 | 仅支持 .docx |

---

## 5. 运行环境约束

### 5.1 Python 版本

- **最低版本**: Python 3.11
- **推荐版本**: Python 3.11.x 或 3.12.x
- **原因**: Pydantic v2 要求 Python 3.8+；FastAPI 要求 Python 3.8+；选择 3.11 以获得最佳性能和兼容性

### 5.2 操作系统

- **开发**: Windows / macOS / Linux
- **生产**: Linux（Docker 容器内）
- **注意**: 文件路径处理使用 `pathlib`，不硬编码路径分隔符

### 5.3 内存

- **最低**: 512MB（单次解析）
- **推荐**: 1GB+
- **说明**: PDF 大文件解析和图片 OCR 可能占用较多内存

### 5.4 网络

- **必须**: 可访问 DeepSeek API（`api.deepseek.com`）
- **必须**: 可访问 DeepSeek-OCR API
- **可选**: 可访问 OpenAI API（降级方案）

---

## 6. 代码组织约束

### 6.1 模块目录结构

```
src/
└── resume_parser/
    ├── __init__.py              # 对外暴露的接口函数
    ├── config.py                # 配置定义（ResumeParserConfig）
    ├── schemas.py               # Pydantic Schema 定义
    ├── parser.py                # 主解析逻辑（parse_resume, parse_resume_text）
    ├── extractors/
    │   ├── __init__.py
    │   ├── pdf_extractor.py     # PDF 文本提取（pdfplumber + PyPDF2）
    │   ├── docx_extractor.py    # DOCX 文本提取
    │   ├── ocr_extractor.py     # 图片 OCR 提取（DeepSeek-OCR）
    │   └── json_importer.py     # JSON 直接导入
    ├── llm/
    │   ├── __init__.py
    │   ├── extractor.py         # LLM 结构化提取
    │   ├── prompt.py            # Prompt 模板管理
    │   └── client.py            # LLM API 客户端封装
    ├── processing/
    │   ├── __init__.py
    │   ├── section_splitter.py  # 语义段落切分
    │   ├── skill_standardizer.py # Skill 标准化
    │   └── pii_encryptor.py     # PII 加密
    ├── utils/
    │   ├── __init__.py
    │   ├── language_detector.py # 语言检测
    │   └── file_utils.py        # 文件工具函数
    └── exceptions.py            # 自定义异常

config/
└── skill_synonyms.json          # Skill 同义词词典
```

### 6.2 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 文件名 | snake_case | `pdf_extractor.py` |
| 类名 | PascalCase | `ResumeSchema` |
| 函数名 | snake_case | `parse_resume()` |
| 常量 | UPPER_SNAKE_CASE | `MAX_FILE_SIZE_MB` |
| 配置项 | snake_case | `llm_base_url` |
| Schema 字段 | snake_case | `full_name` |

---

## 7. 测试约束

### 7.1 测试框架

| 工具 | 用途 |
|------|------|
| `pytest` >= 8.0 | 测试框架 |
| `pytest-asyncio` >= 0.23 | 异步测试支持 |
| `pytest-mock` >= 3.12 | Mock LLM/API 调用 |

### 7.2 测试策略

- **单元测试**: 每个 extractor、processing 模块独立测试
- **集成测试**: `parse_resume` 全流程测试（mock LLM 调用）
- **LLM 测试**: 使用录制回放（recorded responses）测试 LLM 输出解析
- **测试数据**: 使用固定测试文件，不依赖外部服务

### 7.3 测试覆盖率目标

- 核心解析流程: >= 90%
- 边界情况处理: 每个 EC 至少 1 个测试用例
- LLM 相关: mock 测试 + 至少 1 个真实 API 集成测试

---

## 8. 安全约束

| 约束 | 说明 |
|------|------|
| PII 加密 | phone/email 使用 AES-256-GCM 加密 |
| 密钥管理 | 通过环境变量注入，不硬编码 |
| 文件类型白名单 | 仅接受 pdf/docx/jpg/jpeg/png/json |
| 文件大小限制 | 最大 20MB（由 api-layer 校验） |
| LLM Prompt 注入防护 | 不将用户原始输入直接拼接到 System Prompt |
| 日志脱敏 | 日志中不记录 PII 明文 |
