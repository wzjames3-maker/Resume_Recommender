from pathlib import Path
p = Path('pyproject.toml')
text = p.read_text(encoding='utf-8')
text = text.replace('    "flagembedding>=1.1.5",\n', '')
p.write_text(text, encoding='utf-8')
print('removed flagembedding dependency')
