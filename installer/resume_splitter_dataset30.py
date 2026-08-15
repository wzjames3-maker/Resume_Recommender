# coding=utf-8
"""
    @project: MaxKB
    @file： resume_splitter_dataset30.py
    @desc：数据集 30 份简历切片效果测试：label_studio.json OCR 原文 → sanitize(含分号转行) → LLM 切片（不向量化）。
          保真度量 = 非空白字符序列一致（内容无改写，允许空行归属差异）。
          用法：SENSENOVA_API_KEY=... python installer/resume_splitter_dataset30.py [份数默认30] [随机种子默认42]
"""
import json
import os
import random
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps"))

from hr.services.resume_splitter import mask_pii, sanitize_resume_text, split_resume_text  # noqa: E402

_COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 30
_SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 42
LABEL_JSON = "/tmp/ds192080/label_studio.json"
MIN_LEN = 20


def load_tasks():
    with open(LABEL_JSON, encoding="utf-8") as fh:
        tasks = json.load(fh)
    texts = [t["data"]["text"] for t in tasks if t.get("data", {}).get("text")]
    return texts


def sample_texts(texts, count, seed):
    valid = [t for t in texts if len(t) >= MIN_LEN]
    rng = random.Random(seed)
    rng.shuffle(valid)
    return valid[:count]


def strip_ws(s):
    """去除全部空白后比较：判断内容是否无改写（允许空行/换行归属差异）。"""
    return re.sub(r"\s+", "", s)


def main():
    key = os.environ.get("SENSENOVA_API_KEY", "")
    if not key:
        print("SENSENOVA_API_KEY is required")
        return 2
    from openai import OpenAI

    client = OpenAI(api_key=key, base_url="https://token.sensenova.cn/v1")

    def chat_fn(prompt):
        response = client.chat.completions.create(
            model="sensenova-6.8-flash-lite",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("empty LLM response")
        return content

    texts = load_tasks()
    picked = sample_texts(texts, _COUNT, _SEED)
    print("=" * 70)
    print(f"数据集切片测试：总样本 {len(texts)} 份，抽取 {len(picked)} 份（seed={_SEED}），不向量化")
    print("=" * 70)

    rows = []
    t_start = time.time()
    for idx, text in enumerate(picked, 1):
        cleaned = sanitize_resume_text(text)
        stats = {}
        try:
            t0 = time.time()
            chunks = split_resume_text(cleaned, chat_fn, stats=stats)
            elapsed = time.time() - t0
            joined = "".join(c["content"] for c in chunks)
            original_masked = mask_pii(cleaned)
            fidelity = strip_ws(joined) == strip_ws(original_masked)
            # 非空行覆盖：每条原非空行内容都出现在某个 chunk 中
            lines = cleaned.split("\n")
            all_content = "\n".join(c["content"] for c in chunks)
            coverage = all(any(line.strip() and line.strip() in cc for cc in all_content.split("\n")) for line in lines if line.strip())
            pii_hit = any("[已脱敏]" in c["content"] for c in chunks)
            lengths = [len(c["content"]) for c in chunks]
            rows.append({
                "idx": idx, "len_in": len(text), "len_clean": len(cleaned), "lines": len(lines),
                "path": stats.get("path"), "llm_calls": stats.get("llm_calls", 0),
                "n_chunks": len(chunks), "lengths": lengths, "max_len": max(lengths),
                "total_chars": sum(lengths), "fidelity": fidelity, "coverage": coverage,
                "pii_hit": pii_hit, "elapsed_s": round(elapsed, 1), "error": None,
                "titles": [c["title"] for c in chunks],
            })
            print(f"[{idx:02d}] {stats.get('path','?'):>5} 入{len(text):>4}字 清{len(cleaned):>4}字/{len(lines):>2}行 "
                  f"→ {len(chunks):>2}段(最{max(lengths):>3}字) 无改写{'✓' if fidelity else '✗'} "
                  f"覆盖{'✓' if coverage else '✗'} PII{'✓' if pii_hit else '-'} {elapsed:.1f}s", flush=True)
        except Exception as exc:
            rows.append({
                "idx": idx, "len_in": len(text), "len_clean": len(cleaned), "lines": 0,
                "path": "error", "llm_calls": stats.get("llm_calls", 0), "n_chunks": 0,
                "lengths": [], "max_len": 0, "total_chars": 0, "fidelity": False,
                "coverage": False, "pii_hit": False, "elapsed_s": 0,
                "error": str(exc)[:300], "titles": [],
            })
            print(f"[{idx:02d}] ERROR {str(exc)[:160]}")

    total = time.time() - t_start
    print()
    print("=" * 70)
    print("汇总")
    print("=" * 70)
    ok = [r for r in rows if not r["error"]]
    paths = {}
    for r in ok:
        paths[r["path"]] = paths.get(r["path"], 0) + 1
    print(f"完成 {len(ok)}/{len(rows)} 份 | 耗时 {total:.0f}s | LLM 调用 {sum(r['llm_calls'] for r in ok)} 次")
    print(f"路径分布: {paths}")
    if ok:
        print(f"chunk 数: min={min(r['n_chunks'] for r in ok)} avg={statistics.mean(r['n_chunks'] for r in ok):.1f} max={max(r['n_chunks'] for r in ok)}")
        print(f"单段字符: min={min(r['max_len'] for r in ok)} avg(最长大段)={statistics.mean(r['max_len'] for r in ok):.1f} max={max(r['max_len'] for r in ok)}")
        print(f"内容无改写(保真): {sum(1 for r in ok if r['fidelity'])}/{len(ok)}")
        print(f"非空行覆盖: {sum(1 for r in ok if r['coverage'])}/{len(ok)}")
        print(f"PII 掩码命中: {sum(1 for r in ok if r['pii_hit'])}/{len(ok)}")
    errs = [r for r in rows if r["error"]]
    if errs:
        print(f"失败 {len(errs)} 份:")
        for r in errs:
            print(f"  [{r['idx']:02d}] 入{r['len_in']}字 清{r['len_clean']}字: {r['error']}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset30_report.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"seed": _SEED, "count": _COUNT, "rows": rows, "total_s": round(total, 1)}, fh, ensure_ascii=False, indent=1)
    print(f"详细报告: {out}")
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
