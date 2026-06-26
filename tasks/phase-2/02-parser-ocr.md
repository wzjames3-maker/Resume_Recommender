# T-010: DeepSeek-OCR 图片解析

## 基本信息
- 对应 Spec: specs/resume-parser/01-requirements.md REQ-003
- 对应 AC: AC-004
- 依赖: T-009
- 预计工时: 1.5 天

## 输入
- `specs/resume-parser/01-requirements.md` — OCR 相关需求规约
- `src/resume_parser/text_extractor.py` — 文本提取模块（T-009 产出）
- `src/common/config.py` — API Key 等配置

## 输出
- `src/resume_parser/ocr_extractor.py` — OCR 提取模块
- `tests/resume_parser/test_ocr_extractor.py` — 单元测试
- `tests/fixtures/sample_resume.png` — 测试用图片简历
- `tests/fixtures/sample_resume.jpg` — 测试用 JPG 简历

## 实现要求
1. 调用 DeepSeek-OCR API 进行图片文字识别，支持 PNG/JPG/WebP 格式
2. 图片预处理：自动旋转校正、对比度增强、降噪（使用 Pillow）
3. 实现 `OCRExtractor` 类，暴露 `extract(image: bytes) -> ExtractedDocument` 方法
4. OCR 结果需后处理：合并断行、修正常见 OCR 错误（如 0/O 混淆）
5. 支持多页图片批量处理，按页顺序合并结果
6. API 调用失败时自动重试（最多 3 次，指数退避）
7. API Key 从 `config` 读取，禁止硬编码；请求必须设置超时（默认 60s）
8. 关键设计决策：选择 DeepSeek-OCR 而非 Tesseract，因为中文简历识别准确率更高
9. 禁止事项：禁止将 base64 编码的图片直接写入日志；禁止忽略 API 返回的错误码

## 验收检查点

### 前置确认
- [ ] T-009（文本提取）已完成
- [ ] 容器环境已启动
- [ ] DeepSeek-OCR API Key 已配置
- [ ] Pillow 已安装

### AC 验收
- [ ] AC-004: 上传图片格式简历（PNG/JPG），能正确识别文字内容并返回结构化文本，中文识别准确率 ≥ 90%

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] API Key 从 config/env 读取，无硬编码
- [ ] 重试逻辑和超时处理完整
- [ ] 日志中不包含敏感信息（API Key、图片内容）
- [ ] 类型标注完整

### Spec 一致性
- [ ] OCR 输出结构与 `ExtractedDocument` 模型兼容
- [ ] 图片格式支持范围与 REQ-003 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
