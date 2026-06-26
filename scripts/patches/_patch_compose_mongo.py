from pathlib import Path
p = Path('docker-compose.yml')
text = p.read_text(encoding='utf-8')
old = '      - MONGODB_URL=mongodb://mongodb:27017\n'
new = '      - MONGODB_URL=mongodb://admin:password@mongodb:27017/resume_rag?authSource=admin\n'
text = text.replace(old, new)
p.write_text(text, encoding='utf-8')
print('patched docker-compose.yml MONGODB_URL')
