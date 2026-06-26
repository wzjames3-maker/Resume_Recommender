from pathlib import Path
p = Path('Dockerfile')
text = p.read_text(encoding='utf-8')
old = """# 安装系统依赖\nRUN apt-get update && apt-get install -y --no-install-recommends \\\n    build-essential \\\n    curl \\\n    && rm -rf /var/lib/apt/lists/*\n\n# 创建非 root 用户\nRUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser\n\n# 设置工作目录\nWORKDIR /app\n\n# 复制依赖文件\nCOPY pyproject.toml ./\n\n# 安装 Python 依赖\nRUN pip install --no-cache-dir .\n\n# 复制应用代码\nCOPY . .\n\n# 更改文件所有权\nRUN chown -R appuser:appuser /app\n\n# 切换到非 root 用户\nUSER appuser\n\n# 健康检查\nHEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \\\n    CMD curl -f http://localhost:8000/health || exit 1\n"""
new = """# 创建非 root 用户\nRUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser\n\n# 设置工作目录\nWORKDIR /app\n\n# 复制依赖文件\nCOPY pyproject.toml ./\n\n# 安装 Python 依赖\nRUN pip install --no-cache-dir .\n\n# 复制应用代码\nCOPY . .\n\n# 更改文件所有权\nRUN chown -R appuser:appuser /app\n\n# 切换到非 root 用户\nUSER appuser\n\n# 健康检查\nHEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \\\n    CMD python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1\n"""
if old not in text:
    raise SystemExit('Dockerfile target block not found')
p.write_text(text.replace(old, new), encoding='utf-8')
print('simplified Dockerfile')
