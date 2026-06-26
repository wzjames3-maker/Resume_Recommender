# T-041: Docker Compose 生产配置 + 健康检查

## 基本信息
- **对应 Spec**: 生产部署规范
- **对应 AC**: 生产环境可部署、可监控
- **依赖任务**: T-001（Docker Compose 开发配置）, T-039（E2E 测试通过）
- **预计工时**: 1 天
- **优先级**: P1

## 输入
- T-001 产出的 `docker-compose.yml`（开发环境配置）
- 已完成的 FastAPI 应用和 Streamlit 前端
- Nginx 配置需求（可选）

## 输出
- `docker-compose.prod.yml` — 生产环境 Docker Compose 配置
- `docker/nginx/nginx.conf` — Nginx 反向代理配置（可选）
- `docker/Dockerfile.api` — API 服务 Dockerfile（如尚未创建）
- `docker/Dockerfile.frontend` — 前端 Dockerfile（如尚未创建）
- `.env.example` — 环境变量模板

## 实现要求

### docker-compose.prod.yml
1. 服务定义：
   - `api` — FastAPI 后端
   - `frontend` — Streamlit 前端
   - `mongodb` — MongoDB 数据库
   - `milvus` — Milvus 向量库
   - `milvus-etcd` — Milvus 依赖
   - `milvus-minio` — Milvus 存储
   - `nginx` — 反向代理（可选）
2. 所有服务设置 `restart: unless-stopped`
3. 数据卷持久化：MongoDB、Milvus、MinIO 数据
4. 网络隔离：前端网络 + 后端网络 + 数据网络
5. 资源限制：每个服务设置 `deploy.resources.limits`

### 健康检查
每个核心服务配置 `healthcheck`：
- **API**: `curl -f http://localhost:8000/health || exit 1`
- **Frontend**: `curl -f http://localhost:8501/_stcore/health || exit 1`
- **MongoDB**: `mongosh --eval "db.adminCommand('ping')"`
- **Milvus**: `curl -f http://localhost:9091/healthz`
- 依赖服务使用 `depends_on.condition: service_healthy`

### Nginx 反向代理（可选）
- 统一入口：`/` → Streamlit，`/api` → FastAPI
- WebSocket 支持（Streamlit 需要）
- 请求体大小限制（文件上传 10MB）
- 超时配置（SSE 长连接 300s）

### 安全加固
- MongoDB 设置认证（用户名/密码）
- Milvus 设置认证
- API 不暴露调试端口
- 敏感信息通过环境变量注入，不硬编码

## 验收检查点

### 前置确认
- [ ] T-001 开发环境 Docker Compose 可正常运行
- [ ] T-039 E2E 测试通过
- [ ] Docker 已安装

### 部署验证
- [ ] `docker compose -f docker-compose.prod.yml up -d` 成功启动所有服务
- [ ] 所有服务健康检查通过（`docker compose ps` 显示 healthy）
- [ ] 通过 Nginx（或直接）访问前端页面正常
- [ ] 通过 Nginx（或直接）调用 API 正常
- [ ] 数据持久化验证：重启后 MongoDB/Milvus 数据不丢失

### 代码质量
- [ ] `.env.example` 包含所有必需环境变量及说明
- [ ] Dockerfile 使用多阶段构建，镜像体积最小化
- [ ] 无硬编码的密钥或密码
- [ ] 日志输出到 stdout/stderr（便于 `docker compose logs`）

### 通过判定
- [ ] 生产配置可一键启动
- [ ] 健康检查全部通过
- [ ] 重启后服务自动恢复
