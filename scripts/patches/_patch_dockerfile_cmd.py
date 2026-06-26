from pathlib import Path
p = Path('Dockerfile')
text = p.read_text(encoding='utf-8')
old = """CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]"""
new = """CMD ["sh", "-c", "streamlit run src/frontend/app.py --server.port 8501 --server.address 0.0.0.0 & uvicorn src.api.main:app --host 0.0.0.0 --port 8000"]"""
if old not in text:
    raise SystemExit('CMD not found')
text = text.replace(old, new)
p.write_text(text, encoding='utf-8')
print('patched Dockerfile CMD to run both services')
