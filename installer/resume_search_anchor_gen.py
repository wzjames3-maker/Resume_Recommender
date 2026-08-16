# coding=utf-8
"""
    @project: MaxKB
    @file： resume_search_anchor_gen.py
    @date：2026/8/16
    @desc：规模验证语义锚点生成（计划 §3.3 方案 A）：抽样简历 → LLM 切片 → LLM 生成 1-2 条
          「找这类人」查询（禁止姓名/联系方式）→ 锚点 JSON + 人工抽检清单。
          目标 = 该简历的 ls_{idx:04d}.txt（与 resume_ingest_n.py 抽样同 seed，保证在 200 份内）。
          抽检：打开 --review 清单逐条核对查询与简历内容是否相符，不符则从锚点 JSON 删除该条。
          用法：SENSENOVA_API_KEY=... python installer/resume_search_anchor_gen.py [--count 40] [--seed 42]
                [--out /tmp/eval200_semantic_anchors.json] [--review /tmp/anchor_review.txt] [--dry-run]
"""
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maxkb.settings")

import django  # noqa: E402

django.setup()

from hr.services.resume_splitter import split_resume_text  # noqa: E402

LABEL_STUDIO_PATH = "/tmp/ds192080/label_studio.json"
_MIN_TEXT_LENGTH = 20
_MAX_CONTENT_CHARS = 1500  # 生成查询时送入的切片内容上限
_PHONE_RE = re.compile(r"(?:\+?86[\s-]?)?1[3-9]\d(?:[\s-]?\d{4}){2}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_PROMPT_TEMPLATE = """你是招聘专家。下面是某位候选人的简历切片（已脱敏）。请生成 1-2 条「找这类人」的招聘检索查询。

严格规则：
1. 每条查询描述岗位/技能/经验特征（例如「有幕墙系统设计经验、懂 Java 的候选人」），禁止包含姓名、电话、邮箱等个人信息；
2. 查询面向简历库语义检索，5-30 字，自然语言；
3. 只输出 JSON：{{"queries": ["查询1", "查询2"]}}，不要输出其他内容。

简历内容：
{content}"""


def _load_corpus():
    with open(LABEL_STUDIO_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    items = []
    for idx, item in enumerate(data):
        text = (item.get("data") or {}).get("text", "")
        if isinstance(text, str) and len(text) >= _MIN_TEXT_LENGTH:
            items.append({"idx": idx, "text": text})
    return items


def _sample(items, count, seed):
    """与 resume_ingest_n.py 相同抽样逻辑（同 seed 下取同一批简历）。"""
    rng = random.Random(seed)
    rng.shuffle(items)
    return items[:count]


def _chat_fn_factory(api_key):
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://token.sensenova.cn/v1")

    def chat_fn(prompt):
        resp = client.chat.completions.create(
            model="sensenova-6.8-flash-lite",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=2000,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = resp.choices[0].message.content
        if not content:
            raise ValueError("empty LLM response")
        return content

    return chat_fn


def _parse_queries(raw):
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    data = json.loads(text)
    queries = data.get("queries") if isinstance(data, dict) else None
    if not isinstance(queries, list):
        raise ValueError("queries missing or not a list")
    return [q.strip() for q in queries if isinstance(q, str) and q.strip()]


def _is_valid_query(q):
    """长度与 PII 校验：5-60 字、不含电话/邮箱（姓名抽检把关，清单见 --review）。"""
    if not 5 <= len(q) <= 60:
        return False
    if _PHONE_RE.search(q) or _EMAIL_RE.search(q):
        return False
    return True


def _gen_queries(chat_fn, content):
    prompt = _PROMPT_TEMPLATE.format(content=content[:_MAX_CONTENT_CHARS])
    raw = chat_fn(prompt)
    return [q for q in _parse_queries(raw) if _is_valid_query(q)]


def main():
    count, seed = 40, 42
    out_path = "/tmp/eval200_semantic_anchors.json"
    review_path = "/tmp/anchor_review.txt"
    dry_run = False
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--count" and i + 1 < len(args):
            count = int(args[i + 1])
        elif arg == "--seed" and i + 1 < len(args):
            seed = int(args[i + 1])
        elif arg == "--out" and i + 1 < len(args):
            out_path = args[i + 1]
        elif arg == "--review" and i + 1 < len(args):
            review_path = args[i + 1]
        elif arg == "--dry-run":
            dry_run = True
    api_key = os.environ.get("SENSENOVA_API_KEY", "")
    if not dry_run and not api_key:
        print("SENSENOVA_API_KEY is required (or use --dry-run)")
        return 2

    corpus = _load_corpus()
    picked = _sample(corpus, count, seed)
    print(f"语料有效 {len(corpus)} 份，seed={seed} 抽样 {len(picked)} 份生成语义锚点", flush=True)
    if dry_run:
        for item in picked[:5]:
            print(f"  将处理 ls_{item['idx']:04d}.txt（{len(item['text'])} 字）", flush=True)
        print(f"  ...共 {len(picked)} 份（前 5 份预览）", flush=True)
        return 0

    chat_fn = _chat_fn_factory(api_key)
    anchors = []
    review_lines = ["语义锚点抽检清单（逐条核对查询与简历内容是否相符；不符则删除锚点 JSON 中对应条目）", "=" * 70]
    failed = 0
    for item in picked:
        name = f"ls_{item['idx']:04d}.txt"
        try:
            chunks = split_resume_text(item["text"], chat_fn, stats={})
            content = "\n".join(f"【{c['title']}】\n{c['content']}" for c in chunks)
            queries = _gen_queries(chat_fn, content)
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {name}: {str(exc)[:150]}", flush=True)
            continue
        for q in queries:
            anchors.append({"q": q, "targets": [name], "type": "browse",
                            "structured": {"skills": None, "degree": None, "years": None}})
        review_lines.append(f"\n[{name}] 切片 {len(chunks)} 段 / 生成 {len(queries)} 条")
        review_lines.append("  简历内容摘录：" + content[:250].replace("\n", " ").replace("【", "「").replace("】", "」"))
        for q in queries:
            review_lines.append(f"  - 查询：{q}")
        print(f"[ok] {name} 生成 {len(queries)} 条", flush=True)

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(anchors, fh, ensure_ascii=False, indent=1)
    with open(review_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(review_lines))
    print(f"锚点 {len(anchors)} 条 → {out_path}", flush=True)
    print(f"抽检清单 → {review_path}（请逐条核对，不符者从锚点 JSON 删除）", flush=True)
    print(f"失败 {failed} 份", flush=True)
    return 1 if failed > max(1, len(picked) // 10) else 0


if __name__ == "__main__":
    sys.exit(main())
