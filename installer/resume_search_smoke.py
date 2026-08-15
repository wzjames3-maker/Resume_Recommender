# coding=utf-8
"""
    @project: MaxKB
    @file： resume_search_smoke.py
    @date：2026/8/16
    @desc：简历语义检索真实模型冒烟：模式 A（整句双路+RRF+rerank）与模式 B（技能复合）。
          复用 default 工作区已入库简历（resume_pipeline_smoke 产物）+ 已配 LLM/RERANKER 模型。
          用法：SENSENOVA_API_KEY=... SILICONFLOW_API_KEY=... python installer/resume_search_smoke.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maxkb.settings")

import django  # noqa: E402

django.setup()

from hr.serializers.ai import AiService  # noqa: E402
from hr.services.resume_search import search_resumes  # noqa: E402

WORKSPACE = "default"


def main():
    sense_key = os.environ.get("SENSENOVA_API_KEY", "")
    if not sense_key:
        print("SENSENOVA_API_KEY is required")
        return 2
    service = AiService(workspace_id=WORKSPACE, user_id=None, hr_role="ADMIN")
    llm = service._model_or_none()
    rerank = service._rerank_model_or_none()
    print("LLM 已配置:", llm is not None, "| Rerank 已配置:", rerank is not None)

    queries = [
        ("模式A-实体", "有幕墙系统设计经验的候选人", "phrase"),
        ("模式A-技能", "熟悉 Python 和 Django", "phrase"),
        ("模式A-自然语言", "有销售管理经验的候选人", "phrase"),
        ("模式B-技能复合", "会 java python fastapi agent rag 的人", "auto"),
        ("模式B-顺序验证", "精通 java 熟悉 python 了解 rag", "auto"),
    ]
    for label, query, mode in queries:
        print()
        print("=" * 80)
        print(f"[{label}] {query} (mode={mode})")
        print("=" * 80)
        try:
            result = search_resumes(WORKSPACE, query, top_k=5, mode=mode,
                                    hr_role="ADMIN", user_id=None,
                                    llm_model=llm, rerank_model=rerank)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue
        meta = result["meta"]
        print(f"  search_type={meta.get('search_type')} mode={meta.get('mode')} "
              f"skills={meta.get('skills')} rounds={meta.get('rounds')} "
              f"rerank={meta.get('rerank')} 耗时={meta.get('elapsed_ms', {}).get('total')}ms")
        for item in result["items"]:
            cand = item.get("candidate") or {}
            resume = item.get("resume") or {}
            print(f"  #{item['rank']} {cand.get('name', '?')} ({resume.get('file_name', '?')}) "
                  f"score={item.get('score')}")
            for p in item.get("paragraphs", [])[:2]:
                print(f"     段: {p.get('title', '')} :: {str(p.get('content', ''))[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
