# T-001: 容器化环境定义

## 基本信息
- 对应 Spec: tech-decision.md 决策项12
- 对应 AC: 无（基础设施）
- 依赖: 无
- 预计工时: 0.5 天

## 输入
- docs/tech-decision.md

## 输出
- Dockerfile
- docker-compose.yml
- .dockerignore

## 实现要求
1. 创建 Dockerfile，基于 Python 3.11-slim
2. 创建 docker-compose.yml，包含以下服务：
   - app (FastAPI + Streamlit)
   - milvus-standalone (milvusdb/milvus:v2.4.6  # 锁定版本，与 pymilvus >=2.4.6 对齐)
   - mongodb (mongo:7)
   - redis (redis:7-alpine)
   - arq-worker（复用 app 镜像，启动命令: `arq src.common.worker.WorkerSettings`）
   - milvus-etcd
   - milvus-minio
3. 创建 .dockerignore
4. 锁定所有镜像版本
5. 配置 healthcheck
6. Redis 服务配置：redis:7-alpine，端口 6379，appendonly 持久化，healthcheck（redis-cli ping）
7. ARQ Worker 服务配置：复用 app 镜像，启动命令为 arq worker，依赖 redis 服务，restart=unless-stopped

## 验收检查点

### 前置确认
- [ ] docs/tech-decision.md 已读取

### AC 验收
- [ ] docker compose up -d 启动全部服务
- [ ] docker compose ps 全部 healthy
- [ ] app 服务可以访问 /health

### 代码质量
- [ ] Dockerfile 无多余层
- [ ] docker-compose.yml 使用 .env 变量

### Spec 一致性
- [ ] Python 版本 3.11+ 与 tech-decision.md 一致
- [ ] Milvus 使用 Standalone 模式
- [ ] MongoDB 使用 7.x
- [ ] Redis 使用 7.x Alpine，配置 appendonly 持久化

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry < 3 → 修复 | retry = 3 → BLOCKED
