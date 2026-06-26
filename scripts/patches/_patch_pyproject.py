from pathlib import Path
p = Path('pyproject.toml')
text = p.read_text(encoding='utf-8')
old = 'readme = "README.md"'
new = 'readme = {text="", content-type="text/plain"}'
if old not in text:
    raise SystemExit('readme line not found')
p.write_text(text.replace(old, new), encoding='utf-8')
print('patched pyproject.toml readme')
