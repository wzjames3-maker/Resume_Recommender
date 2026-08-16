# coding=utf-8
"""
    @project: MaxKB
    @file： resume_search_eval.py
    @date：2026/8/16
    @desc：检索量化对比（阶段 3.3）：12 锚点查询 × 四路语义（dense/RRF/RRF+rerank/Skill-AND）
          + 结构化基线（Candidate.skills/degree/years 组合过滤）。
          指标：recall@5、recall@3、Top-1 准确率、MRR。
          用法：SENSENOVA_API_KEY=... python installer/resume_search_eval.py
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

# 锚点查询集：{query, targets: [目标简历 file_name], type, structured: {skills/degree/years}（结构化基线条件）}
ANCHORS = [
    {"q": "有幕墙系统设计经验的候选人", "targets": ["resume_0000_李冠光.txt"], "type": "实体",
     "structured": {"skills": ["幕墙"], "degree": None, "years": None}},
    {"q": "做过 Unity 场景搭建和灯光渲染的人", "targets": ["cbb7a43eb62f.docx"], "type": "技能",
     "structured": {"skills": ["unity"], "degree": None, "years": None}},
    {"q": "有销售管理经验的人", "targets": ["resume_0001_乐志昌.txt", "resume_0017_昌娜.txt"], "type": "自然语言",
     "structured": {"skills": ["销售"], "degree": None, "years": None}},
    {"q": "做过会计工作的候选人", "targets": ["resume_0007_马风.txt", "resume_0026_鲁云玉.txt"], "type": "实体",
     "structured": {"skills": ["会计"], "degree": None, "years": None}},
    {"q": "有教育或培训经历的教师", "targets": ["resume_0006_和君英.txt"], "type": "自然语言",
     "structured": {"skills": ["教师"], "degree": None, "years": None}},
    {"q": "有招聘经验的 HR", "targets": ["resume_0008_谈菁咏.txt"], "type": "实体",
     "structured": {"skills": ["招聘"], "degree": None, "years": None}},
    {"q": "熟悉新媒体运营的人", "targets": ["resume_0004_彭子.txt"], "type": "技能",
     "structured": {"skills": ["新媒体"], "degree": None, "years": None}},
    {"q": "有平面设计经验的候选人", "targets": ["resume_0014_邬和.txt"], "type": "实体",
     "structured": {"skills": ["平面设计"], "degree": None, "years": None}},
    {"q": "负责过门店经营和数据分析的楼面经理", "targets": ["resume_0018_谈伯义.txt"], "type": "自然语言",
     "structured": {"skills": ["楼面"], "degree": None, "years": None}},
    {"q": "有物流管理经验的专员", "targets": ["resume_0022_施先亮.txt"], "type": "实体",
     "structured": {"skills": ["物流"], "degree": None, "years": None}},
    {"q": "有对外联络和政府沟通经验的人", "targets": ["resume_0015_皮云.txt"], "type": "自然语言",
     "structured": {"skills": ["外联"], "degree": None, "years": None}},
    {"q": "做过机电质检的经理", "targets": ["resume_0005_酆娜.txt"], "type": "实体",
     "structured": {"skills": ["质检"], "degree": None, "years": None}},
]


def build_typed_anchors(count: int = 10):
    """程序化生成 typed 锚点（无需人工标注，v2 评测 §6）：
    lookup：候选人姓名（验证姓名快速通道）；conditional：年限/学历/城市槽位（验证结构化预筛）。
    目标 = 该候选人当前简历文件。"""
    import random

    from django.db.models import QuerySet

    from hr.models import Candidate, ResumeFile

    anchors = []
    candidates = list(QuerySet(Candidate).filter(workspace_id=WORKSPACE, status="ACTIVE"))
    rng = random.Random(42)
    rng.shuffle(candidates)
    picked = candidates[:count]
    for cand in picked:
        rf = QuerySet(ResumeFile).filter(candidate_id=cand.id, document_id__isnull=False).first()
        if rf is None:
            continue
        target = rf.file_name
        base = {"skills": None, "degree": None, "years": None}
        if cand.name:
            anchors.append({"q": cand.name, "targets": [target], "type": "lookup", "structured": base})
        if cand.years_experience:
            anchors.append({"q": f"{cand.years_experience}年以上", "targets": [target], "type": "conditional",
                            "structured": {**base, "years": cand.years_experience}})
        if cand.highest_degree:
            anchors.append({"q": cand.highest_degree, "targets": [target], "type": "conditional",
                            "structured": {**base, "degree": cand.highest_degree}})
        if cand.current_city:
            anchors.append({"q": cand.current_city, "targets": [target], "type": "conditional",
                            "structured": base})
    return anchors


def load_anchors():
    """基础锚点 + （--typed [N] 时）程序化 typed 锚点。"""
    if "--typed" in sys.argv:
        count = 10
        idx = sys.argv.index("--typed")
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            count = int(sys.argv[idx + 1])
        return ANCHORS + build_typed_anchors(count)
    return ANCHORS


def main():
    sense_key = os.environ.get("SENSENOVA_API_KEY", "")
    if not sense_key:
        print("SENSENOVA_API_KEY is required")
        return 2
    anchors = load_anchors()
    service = AiService(workspace_id=WORKSPACE, user_id=None, hr_role="ADMIN")
    llm = service._model_or_none()
    rerank = service._rerank_model_or_none()
    print("LLM:", llm is not None, "Rerank:", rerank is not None)

    modes = [
        ("dense", {"mode": "dense"}),
        ("RRF", {"mode": "phrase"}),
        ("RRF+rerank", {"mode": "phrase", "rerank": True}),
        ("Skill-AND", {"mode": "auto"}),
    ]
    results = {name: [] for name, _ in modes}
    errors = {name: 0 for name, _ in modes}
    for anchor in ANCHORS:
        q, targets = anchor["q"], anchor["targets"]
        print(f"\n=== [{anchor['type']}] {q} → {targets}")
        for name, opts in modes:
            try:
                result = search_resumes(
                    WORKSPACE, q, top_k=5, mode=opts["mode"],
                    hr_role="ADMIN", user_id=None,
                    llm_model=llm, rerank_model=rerank if opts.get("rerank") else None,
                )
            except Exception as exc:
                # 异常锚点不参与分母（记入警告，便于复核口径）
                results[name].append(False)
                errors[name] += 1
                print(f"  {name}: ERROR {str(exc)[:80]}")
                continue
            items = result["items"]
            hit_names = [it["resume"]["file_name"] for it in items if it.get("resume")]
            hit = [t for t in targets if t in hit_names]
            rank_of = {}
            for idx, it in enumerate(items, 1):
                fn = it["resume"]["file_name"] if it.get("resume") else None
                if fn in targets and fn not in rank_of:
                    rank_of[fn] = idx
            # MRR 口径：全部相关目标的 1/rank 均值（非标准 first-relevant MRR；多目标锚点数值系统性偏低，
            # 仅用于模式间横向对比，与审计报告口径一致）
            mrr = sum(1.0 / r for r in rank_of.values()) / len(targets) if rank_of else 0
            results[name].append((bool(hit), rank_of, mrr))
            print(f"  {name}: hits={hit_names[:5]} 命中={hit} MRR={mrr:.3f}")

    # 结构化基线：Candidate.skills 含 skills 任一项
    from hr.models import Candidate
    from django.db.models import QuerySet
    struct_results = []
    for anchor in anchors:
        cond = anchor["structured"]
        skills = [s.lower() for s in (cond["skills"] or [])]
        cands = list(QuerySet(Candidate).filter(workspace_id=WORKSPACE, status="ACTIVE"))
        hit_names = []
        for c in cands:
            c_skills = [s.lower() for s in (c.skills or [])]
            if any(s in " ".join(c_skills) for s in skills):
                from hr.models import ResumeFile
                rf = QuerySet(ResumeFile).filter(candidate_id=c.id).first()
                if rf:
                    hit_names.append(rf.file_name)
        hit = [t for t in anchor["targets"] if t in hit_names]
        rank = 0
        for idx, fn in enumerate(hit_names[:5], 1):
            if fn in anchor["targets"]:
                rank = idx
                break
        # 与语义模式相同的四指标口径（此前仅 recall@5/MRR，报告表格中的 recall@3/Top-1 无法由脚本复现）
        struct_results.append((bool(hit), rank))
        print(f"  结构化基线: {hit_names[:5]} 命中={hit} Top-1={1 if rank == 1 else 0}")

    # 汇总
    print("\n" + "=" * 70)
    print(f"汇总（{len(anchors)} 锚点查询）")
    print("=" * 70)
    for name, _ in modes:
        rows = results[name]
        ok = [r for r in rows if isinstance(r, tuple)]
        recall5 = sum(1 for r in ok if r[0]) / len(ok)
        recall3 = sum(1 for r in ok if any(v <= 3 for v in r[1].values())) / len(ok)
        top1 = sum(1 for r in ok if any(v == 1 for v in r[1].values())) / len(ok)
        mrr = sum(r[2] for r in ok) / len(ok)
        print(f"{name:>12}: recall@5={recall5:.2f} recall@3={recall3:.2f} Top-1={top1:.2f} MRR={mrr:.3f}")
        if errors[name]:
            print(f"           ⚠ {errors[name]} 个锚点异常被剔除（不计入分母）")
    ok = [r for r in struct_results if isinstance(r, tuple)]
    recall5 = sum(1 for r in ok if r[0]) / len(ok)
    recall3 = sum(1 for r in ok if r[1] and r[1] <= 3) / len(ok)
    top1 = sum(1 for r in ok if r[1] == 1) / len(ok)
    mrr = sum(1.0 / r[1] for r in ok if r[1]) / len(ok)
    print(f"{'结构化基线':>12}: recall@5={recall5:.2f} recall@3={recall3:.2f} Top-1={top1:.2f} MRR={mrr:.3f}")

    # 分类型指标（v2 评测 §6）：每种锚点类型 × 每种模式的 recall@5/MRR
    print("\n分类型指标（recall@5 / MRR）")
    types = sorted({a["type"] for a in anchors})
    header = "".join(f" {name:>16}" for name, _ in modes)
    print(f"{'类型':<12}{header}")
    for t in types:
        row = f"{t:<12}"
        for name, _ in modes:
            rows = [results[name][i] for i, a in enumerate(anchors)
                    if a["type"] == t and isinstance(results[name][i], tuple)]
            if rows:
                r5 = sum(1 for r in rows if r[0]) / len(rows)
                mrr = sum(r[2] for r in rows) / len(rows)
                row += f" {r5:.2f}/{mrr:.3f}".rjust(17)
            else:
                row += f" {'-':>16}"
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
