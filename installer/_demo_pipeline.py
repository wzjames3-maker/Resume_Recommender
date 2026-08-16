# coding=utf-8
"""简历处理全流程节点数据演示（原始 OCR 分号流样本 → 清洗 → 切片 → 向量化 → 检索）"""
import json
import math
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps"))

from hr.services.resume_splitter import sanitize_resume_text, split_resume_text  # noqa: E402
from openai import OpenAI  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = open(os.path.join(ROOT, "testdata", "original_sample.txt"), encoding="utf-8").read()
SENSE_KEY = os.environ.get("SENSENOVA_API_KEY", "")
SILICON_KEY = os.environ.get("SILICONFLOW_API_KEY", "")

print("=" * 70)
print("节点 0：原始简历（数据集原文，未处理）")
print("-" * 70)
print("长度:", len(SAMPLE), "字符 | 换行数:", SAMPLE.count("\n"))
print(SAMPLE[:600].replace("\n", "⏎"))
print("...")

# ---------- 节点 1：清洗 ----------
cleaned = sanitize_resume_text(SAMPLE)
print()
print("=" * 70)
print("节点 1：sanitize_resume_text() 清洗后")
print("-" * 70)
print("长度:", len(cleaned), "| 换行数:", cleaned.count("\n"), "| 变化:", "无（原始即无控制字符/多空格）" if len(cleaned) == len(SAMPLE) else "有")
print(cleaned[:400].replace("\n", "⏎"))

# ---------- 节点 2：LLM 边界标注切片 ----------
llm = OpenAI(api_key=SENSE_KEY, base_url="https://token.sensenova.cn/v1")

def chat_fn(prompt):
    resp = llm.chat.completions.create(
        model="sensenova-6.8-flash-lite",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1, max_tokens=2000,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return resp.choices[0].message.content

print()
print("=" * 70)
print("节点 2：ResumeSplitter（LLM 行号边界标注 + 校验 + 降级）")
print("-" * 70)
lines = cleaned.split("\n")
print("行数:", len(lines), "→ LLM 输入的编号文本（前 120 字）：")
print("1  " + cleaned[:120].replace("\n", "⏎"))
chunks = split_resume_text(cleaned, chat_fn)
print("→ 切片结果:", len(chunks), "段")
for i, chunk in enumerate(chunks):
    print("  [%d] title=%r (%d字) %s..." % (i + 1, chunk["title"], len(chunk["content"]), chunk["content"][:70].replace("\n", "⏎")))
    if "15004981036" in chunk["content"] or "@" in chunk["content"]:
        print("      ↑ 含 PII，已掩码:", "[已脱敏]" in chunk["content"])
# ---------- 节点 3：向量化 ----------

def embed_one(text):
    req = urllib.request.Request(
        "https://api.siliconflow.cn/v1/embeddings",
        data=json.dumps({"model": "BAAI/bge-large-zh-v1.5", "input": [text], "encoding_format": "float"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + SILICON_KEY},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())["data"][0]["embedding"]

print()
print("=" * 70)
print("节点 3：向量化（SiliconFlow bge-large-zh-v1.5，逐段 embed）")
print("-" * 70)
vecs = []
for i, chunk in enumerate(chunks):
    vec = embed_one(chunk["content"])
    vecs.append(vec)
    norm = math.sqrt(sum(x * x for x in vec))
    print("  段[%d] 维度=%d 前5维=[%s] 范数=%.4f" % (
        i + 1, len(vec), ", ".join("%.4f" % x for x in vec[:5]), norm))

# ---------- 节点 4：检索 ----------
query = "有行政后勤管理经验的候选人，负责过制度建设和绩效考核"
print()
print("=" * 70)
print("节点 4：检索（查询 → 各段余弦相似度排序）")
print("-" * 70)
print("查询:", query)
qv = embed_one(query)

def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

ranked = sorted(range(len(chunks)), key=lambda i: -cos(qv, vecs[i]))
for rank, i in enumerate(ranked[:3], 1):
    print("  #%d 相似度=%.4f %s..." % (rank, cos(qv, vecs[i]), chunks[i]["content"][:60].replace("\n", "⏎")))
print()
print("=" * 70)
print("全流程完成：原始 %d 字 → 清洗 %d 字 → 切片 %d 段 → 向量 %d 条 → 检索排序" % (
    len(SAMPLE), len(cleaned), len(chunks), len(vecs)))
