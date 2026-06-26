import re
from pathlib import Path
p = Path('.env')
text = p.read_text(encoding='utf-8')
text = re.sub(r'^MONGODB_AUTH_SOURCE=.*\n?', '', text, flags=re.MULTILINE)
text = re.sub(r'^MONGODB_URL=.*$', 'MONGODB_URL=mongodb://admin:password@localhost:27017/resume_rag?authSource=admin', text, flags=re.MULTILINE)
p.write_text(text, encoding='utf-8')
print('updated .env with authSource in URL')
