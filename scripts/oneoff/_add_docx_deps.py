from pathlib import Path
p = Path('pyproject.toml')
text = p.read_text(encoding='utf-8')
additions = ['    "python-docx>=1.1.0",\n', '    "pdfplumber>=0.11.0",\n']
for dep in additions:
    if dep.strip().split('>')[0].strip('" ') not in text:
        text = text.replace('    "python-multipart>=0.0.6",\n', '    "python-multipart>=0.0.6",\n' + dep)
p.write_text(text, encoding='utf-8')
print('added docx/pdf deps')
