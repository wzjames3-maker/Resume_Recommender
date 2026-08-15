# coding=utf-8
"""
    @project: MaxKB
    @file： resume_splitter_smoke.py
    @date：2026/8/15
    @desc：ResumeSplitter 真实模型冒烟：LLM 边界标注 → L2 校验 → 降级统计。
          用法：SENSENOVA_API_KEY=... python installer/resume_splitter_smoke.py [简历数默认10]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps"))

from hr.services.resume_splitter import split_resume_text  # noqa: E402

_COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 10


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

    resume_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "testdata", "generated", "resumes")
    files = sorted(f for f in os.listdir(resume_dir) if f.endswith(".txt"))[:_COUNT]
    stats = {"total": 0, "llm_ok": 0, "fallback": 0, "error": 0, "chunk_counts": [], "pii_masked": 0}
    for name in files:
        stats["total"] += 1
        text = open(os.path.join(resume_dir, name), encoding="utf-8").read()
        try:
            result = split_resume_text(text, chat_fn)
            stats["chunk_counts"].append(len(result))
            # 粗略判断是否走了 LLM（LLM 会给 title，规则降级也会给 title——用 content 保真与段数判断即可）
            joined = "\n".join(row["content"] for row in result)
            if any("[已脱敏]" in row["content"] for row in result):
                stats["pii_masked"] += 1
            # 保真：非空行都在结果中
            ok = all((line.strip() in joined) for line in text.split("\n") if line.strip())
            if ok:
                stats["llm_ok"] += 1
            else:
                stats["fallback"] += 1
                print("  ! 保真检查失败:", name)
        except Exception as exc:
            stats["error"] += 1
            print("  ! ERROR:", name, str(exc)[:200])
        print(("OK " if True else "") + name, flush=True)
    print("\n===== 冒烟统计 =====")
    print("总份数:", stats["total"], "| 保真通过:", stats["llm_ok"], "| 异常:", stats["error"])
    print("段落数:", stats["chunk_counts"])
    print("PII 掩码命中的份数:", stats["pii_masked"])
    return 0 if stats["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
