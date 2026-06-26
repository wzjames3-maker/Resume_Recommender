from pathlib import Path
p = Path('Dockerfile')
text = p.read_text(encoding='utf-8')
old = """# 复制依赖文件\nCOPY pyproject.toml poetry.lock* ./\n\n# 安装 Python 依赖\nRUN pip install --no-cache-dir poetry && \\\n    poetry config virtualenvs.create false && \\\n    poetry install --no-interaction --no-ansi\n\n# 复制应用代码\nCOPY . .\n"""
new = """# 复制依赖文件\nCOPY pyproject.toml ./\n\n# 安装 Python 依赖\nRUN pip install --no-cache-dir .\n\n# 复制应用代码\nCOPY . .\n"""
if old not in text:
    raise SystemExit('Dockerfile target block not found')
p.write_text(text.replace(old, new), encoding='utf-8')
print('patched Dockerfile')
