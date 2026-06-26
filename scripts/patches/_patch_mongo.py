from pathlib import Path
p = Path('src/resume_store/connection.py')
text = p.read_text(encoding='utf-8')
old = """        try:\n            self._client = MongoClient(\n                mongodb_url,\n                serverSelectionTimeoutMS=5000,\n                connectTimeoutMS=10000,\n            )\n\n            # 测试连接\n            self._client.admin.command(\"ping\")\n\n            # 获取数据库\n            self._database = self._client[settings.mongodb.MONGODB_DATABASE]\n"""
new = """        try:\n            self._client = MongoClient(\n                mongodb_url,\n                username=settings.mongodb.MONGODB_USER or None,\n                password=settings.mongodb.MONGODB_PASSWORD or None,\n                authSource=\"admin\",\n                serverSelectionTimeoutMS=5000,\n                connectTimeoutMS=10000,\n            )\n\n            # 测试连接\n            self._client.admin.command(\"ping\")\n\n            # 获取数据库\n            self._database = self._client[settings.mongodb.MONGODB_DATABASE]\n"""
if old not in text:
    raise SystemExit('target block not found')
p.write_text(text.replace(old, new), encoding='utf-8')
print('patched src/resume_store/connection.py')
