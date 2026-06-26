from pathlib import Path
p = Path('src/resume_store/connection.py')
text = p.read_text(encoding='utf-8')
old = """            self._client = MongoClient(\n                mongodb_url,\n                username=settings.mongodb.MONGODB_USER or None,\n                password=settings.mongodb.MONGODB_PASSWORD or None,\n                authSource=\"admin\",\n                serverSelectionTimeoutMS=5000,\n                connectTimeoutMS=10000,\n            )\n"""
new = """            self._client = MongoClient(\n                mongodb_url,\n                serverSelectionTimeoutMS=5000,\n                connectTimeoutMS=10000,\n            )\n"""
if old not in text:
    raise SystemExit('connection patch target not found')
p.write_text(text.replace(old, new), encoding='utf-8')
print('simplified MongoDB connection')
