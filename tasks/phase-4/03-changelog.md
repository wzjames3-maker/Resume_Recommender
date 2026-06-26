# T-042: CHANGELOG.md + 版本标记

## 基本信息
- **对应 Spec**: 项目文档规范
- **对应 AC**: 版本可追溯
- **依赖任务**: T-041（Docker Compose 生产配置）
- **预计工时**: 0.5 天
- **优先级**: P1

## 输入
- 项目完整任务列表和完成记录（`tasks/` 目录）
- Git 提交历史
- PRD（`docs/PRD.md`）中的功能需求

## 输出
- `CHANGELOG.md` — 变更日志
- Git tag `v1.0.0` — 版本标记

## 实现要求

### CHANGELOG.md 格式
遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范：

```markdown
# Changelog

## [1.0.0] - 2026-06-23

### Added
- 用户认证：JWT 登录/登出
- 简历上传：支持 PDF/DOCX/DOC 格式
- 智能搜索：自然语言输入 → 候选人推荐
- 多轮对话：基于上下文的 refine 搜索
- 候选人卡片：技能、经验、匹配度展示
- 对话管理：创建、查看、删除对话
- Audit Log：全量 API 请求审计日志
- Docker Compose 一键部署
- API 文档：Swagger UI + ReDoc

### Technical
- 后端: FastAPI + Python 3.11
- 前端: Streamlit
- 数据库: MongoDB
- 向量库: Milvus
- LLM: OpenAI API
- 检索: Hybrid Retrieval（向量 + 关键词）+ Rerank

### Infrastructure
- Docker Compose 开发/生产环境配置
- 健康检查与自动重启
- Nginx 反向代理（可选）
```

### 版本标记
1. 在 CHANGELOG 完成后，创建 Git tag `v1.0.0`
2. Tag message 与 CHANGELOG 首条一致

## 验收检查点

### 前置确认
- [ ] T-041 已完成并通过验收
- [ ] 所有功能任务已完成

### 文档质量
- [ ] CHANGELOG 覆盖所有主要功能
- [ ] 日期格式正确
- [ ] 分类合理（Added / Changed / Fixed / Technical / Infrastructure）

### 通过判定
- [ ] CHANGELOG.md 内容准确完整
- [ ] Git tag v1.0.0 已创建
- [ ] 无遗漏的重要功能或变更
