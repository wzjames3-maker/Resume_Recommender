from pathlib import Path
# patch pyproject
p = Path('pyproject.toml')
text = p.read_text(encoding='utf-8')
if 'cryptography' not in text:
    text = text.replace('    "pyjwt>=2.8.0",\n', '    "pyjwt>=2.8.0",\n    "cryptography>=42.0.0",\n')
    p.write_text(text, encoding='utf-8')
    print('added cryptography dependency')
else:
    print('cryptography already present')

# patch worker
w = Path('src/common/worker.py')
text = w.read_text(encoding='utf-8')
old = """from arq import cron\nfrom arq.connections import RedisSettings\n"""
new = """import os\n\nfrom arq import cron\nfrom arq.connections import RedisSettings\n"""
if old in text:
    text = text.replace(old, new)
old2 = """    redis_settings = RedisSettings(\n        host=\"redis\",\n        port=6379,\n        database=0,\n    )\n"""
new2 = """    redis_settings = RedisSettings(\n        host=\"redis\",\n        port=6379,\n        database=0,\n        password=os.environ.get(\"REDIS_PASSWORD\", \"password\"),\n    )\n"""
if old2 not in text:
    raise SystemExit('worker patch target not found')
text = text.replace(old2, new2)
w.write_text(text, encoding='utf-8')
print('patched worker redis settings')
