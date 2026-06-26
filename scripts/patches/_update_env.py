import re
from pathlib import Path
p = Path('.env')
text = p.read_text(encoding='utf-8')
additions = [
    'MONGODB_AUTH_SOURCE=admin',
    'MONGODB_PORT=27017',
    'MILVUS_PORT=19530',
    'MINIO_ACCESS_KEY=minioadmin',
    'MINIO_SECRET_KEY=minioadmin',
]
for line in additions:
    key = line.split('=',1)[0]
    pattern = re.compile(rf'^{key}=.*$', re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(line, text)
    else:
        text = text.rstrip() + '\n' + line + '\n'
p.write_text(text, encoding='utf-8')
print('updated .env')
