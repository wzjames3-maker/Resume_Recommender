# T-009: PDF/DOCX 文本提取

## 基本信息
- 对应 Spec: specs/resume-parser/01-requirements.md REQ-001, REQ-002
- 对应 AC: AC-001~AC-003, AC-005, AC-011, AC-012, AC-014
- 依赖: T-002, T-003
- 预计工时: 2 天

## 输入
- `specs/resume-parser/01-requirements.md` — 文本提取需求规约
- `specs/resume-parser/02-data-model.md` — Resume 原始数据模型
- `src/common/config.py` — 全局配置（T-002 产出）
- `src/common/exceptions.py` — 自定义异常（T-003 产出）

## 输出
- `src/resume_parser/text_extractor.py` — 文本提取核心模块
- `src/resume_parser/__init__.py` — 模块初始化
- `tests/resume_parser/test_text_extractor.py` — 单元测试
- `tests/fixtures/sample.pdf` — 测试用 PDF 样本
- `tests/fixtures/sample.docx` — 测试用 DOCX 样本

## 实现要求
1. 使用 `pdfplumber` 提取 PDF 文本，保留段落结构和换行信息；`pdfplumber` 不可用时回退到 `PyPDF2`
2. 使用 `python-docx` 提取 DOCX 文本，处理段落、表格、列表等结构
3. 统一输出格式为 `ExtractedDocument` Pydantic 模型，包含 `raw_text: str`、`page_texts: list[str]`、`metadata: dict`（文件名、页数、提取时间等）
4. 对加密/受保护的 PDF/DOCX 抛出 `ProtectedFileError`，对损坏文件抛出 `CorruptedFileError`
5. 提取的文本必须去除页眉页脚重复内容，合并跨页断行
6. 文件大小限制：单文件不超过 50MB，超出抛出 `FileSizeExceededError`
7. 支持 JSON 格式简历直接导入：JSON 输入跳过文本提取流程，直接映射为 ResumeStructured Pydantic 模型（对齐 REQ-004）
8. 所有提取操作必须有超时控制（默认 30s），超时抛出 `ExtractionTimeoutError`
8. 关键设计决策：选择 pdfplumber 而非 PyPDF2 作为首选，因为 pdfplumber 对表格和布局的保留更好；保留 PyPDF2 作为 fallback
9. 禁止事项：禁止在内存中同时加载整个大文件，必须流式处理；禁止忽略提取错误静默返回空结果

## 验收检查点

### 前置确认
- [ ] T-002（全局配置）已完成
- [ ] T-003（异常体系）已完成
- [ ] 容器环境已启动
- [ ] pdfplumber, PyPDF2, python-docx 已安装

### AC 验收
- [ ] AC-001: 上传 PDF 文件后能正确提取全部文本内容，段落结构保留
- [ ] AC-002: 上传 DOCX 文件后能正确提取全部文本内容，表格和列表正确解析
- [ ] AC-003: 提取结果包含文件元数据（文件名、页数、提取耗时）

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] 无硬编码的文件路径或超时值，全部从 config 读取
- [ ] 错误处理完整：ProtectedFileError / CorruptedFileError / FileSizeExceededError / ExtractionTimeoutError 均有对应处理
- [ ] 类型标注完整
- [ ] docstring 覆盖所有公开方法


- [ ] AC-011: 加密 PDF 文件输入时，抛出 ProtectedFileError 并给出明确提示
- [ ] AC-012: 扫描件 PDF（纯图片）输入时，自动走 OCR 降级路径（调用 T-010 模块）
- [ ] AC-014: 空文件（0 字节）输入时，抛出 EmptyFileError，不写入任何数据


- [ ] AC-005: JSON 格式简历导入时，直接映射为 ResumeStructured Schema，跳过文本提取和 LLM 解析步骤

### Spec 一致性
- [ ] 输出数据结构与 `specs/resume-parser/02-data-model.md` 中 `ExtractedDocument` 定义一致
- [ ] 文件大小限制与 spec 中 REQ-001 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
