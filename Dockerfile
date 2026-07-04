# 智能招聘 RAG 推荐系统 - Dockerfile
# 基于 Python 3.11-slim

FROM python:3.11-slim AS base

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY pyproject.toml ./

# 安装 Python 依赖（含 milvus-lite 用于测试）
RUN pip install --no-cache-dir ".[dev]" && pip install --no-cache-dir "pymilvus[milvus_lite]"

# 复制应用代码
COPY . .

# 更改文件所有权
RUN chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 暴露端口
EXPOSE 8000 8501

# 默认启动命令（仅 FastAPI，前端用独立服务）
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
