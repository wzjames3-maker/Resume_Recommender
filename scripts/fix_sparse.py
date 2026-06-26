import re

with open("src/vector_index/embedding_generator.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace the _dense_to_sparse method to return empty dict
# Match from "def _dense_to_sparse" to the next "def " or end of class
pattern = r'(    def _dense_to_sparse\(self, dense: List\[float\]\) -> Dict\[int, float\]:\n).*?(?=\n    def |\n\n# |\nclass |\Z)'

replacement = r'\1        """Return empty dict. SiliconFlow /v1/embeddings does not expose BGE-M3 native sparse.\n        Rely on dense embedding + bge-reranker-v2-m3 for retrieval quality."""\n        return {}\n'

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

if new_content != content:
    with open("src/vector_index/embedding_generator.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("OK: _dense_to_sparse now returns empty dict")
else:
    print("WARN: pattern not matched")
