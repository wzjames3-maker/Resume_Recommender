#!/bin/bash
# 智能招聘 RAG 推荐系统 - 启动脚本

set -e

echo "=========================================="
echo "智能招聘 RAG 推荐系统 - 启动脚本"
echo "=========================================="

# 激活虚拟环境
if [ -d ".venv" ]; then
    echo "激活虚拟环境..."
    source .venv/bin/activate
fi

# 检查 Docker 服务
echo ""
echo "检查 Docker 服务..."
docker compose ps

# 启动 FastAPI 应用
echo ""
echo "启动 FastAPI 应用..."
echo "API 文档: http://localhost:8000/docs"
echo "健康检查: http://localhost:8000/health"
echo ""

python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
