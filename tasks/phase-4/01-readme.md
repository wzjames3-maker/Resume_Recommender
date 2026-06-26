# T-040: README.md + 部署文档

## 基本信息
- **对应 Spec**: 项目文档规范
- **对应 AC**: 项目可理解性、可部署性
- **依赖任务**: T-039（E2E 测试通过，代表功能完整）
- **预计工时**: 0.5 天
- **优先级**: P1

## 输入
- 已完成的项目代码（src/ 目录）
- 已完成的 API 端点（T-030 ~ T-033）
- Docker Compose 配置（T-001 产出）
- 技术选型文档（`docs/tech-decision.md`）
- PRD（`docs/PRD.md`）

## 输出
- `README.md` — 项目主文档
- `docs/deployment.md` — 部署文档
- `docs/api-reference.md` — API 文档索引（可选，或链接到 Swagger）

## 实现要求

### README.md 结构
```markdown
# 简历推荐系统

## 项目简介
一段话描述项目功能和目标用户

## 架构图
Mermaid 或 ASCII 架构图（前端 → API → 检索层 → 存储层）

## 快速启动
### 环境要求
- Docker + Docker Compose
- Python 3.11+

### 启动步骤
1. 克隆仓库
2. 复制 .env.example → .env
3. docker compose up -d
4. 访问 http://localhost:8501

### 默认账号
- admin / admin123（首次登录后请修改密码）

## API 文档
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 技术栈
- 后端: FastAPI + Python
- 前端: Streamlit
- 数据库: MongoDB
- 向量库: Milvus
- LLM: OpenAI API

## 项目结构
简要目录树说明

## 开发指南
### 本地开发
### 运行测试
### 代码规范

## License
```

### 部署文档
1. 生产环境部署步骤（Docker Compose）
2. 环境变量说明（`.env.example` 中所有变量）
3. 数据备份与恢复
4. 日志查看方式
5. 常见问题排查

## 验收检查点

### 前置确认
- [ ] T-039 已完成并通过验收
- [ ] 项目可正常启动并运行

### 文档质量
- [ ] README 中的快速启动步骤可从零执行成功
- [ ] 架构图准确反映实际系统结构
- [ ] 所有环境变量有说明
- [ ] API 文档链接可用

### 通过判定
- [ ] 新成员按 README 步骤可在 30 分钟内启动项目
- [ ] 部署文档覆盖生产环境部署全流程
- [ ] 无过时或错误信息
