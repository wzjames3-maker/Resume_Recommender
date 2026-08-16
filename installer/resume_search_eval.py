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
    from hr.services.query_understand import _DEGREE_LEVELS

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
        # A2 复审：仅词表内学历生成 degree 锚点（高中/中专等 extract_slots 无法结构化，查询不可靠）
        if cand.highest_degree and cand.highest_degree in _DEGREE_LEVELS:
            anchors.append({"q": cand.highest_degree, "targets": [target], "type": "conditional",
                            "structured": {**base, "degree": cand.highest_degree}})
        if cand.current_city:
            anchors.append({"q": cand.current_city, "targets": [target], "type": "conditional",
                            "structured": {**base, "city": cand.current_city}})
    return anchors  # P2-B 复审：F8 提交误删本行导致 --typed 时 ANCHORS + None TypeError


def load_anchors():
    """基础锚点 + （--typed [N]）typed 锚点 + （--semantic-anchors PATH）语义锚点（规模验证 §3）。"""
    anchors = ANCHORS
    if "--typed" in sys.argv:
        count = 10
        idx = sys.argv.index("--typed")
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            count = int(sys.argv[idx + 1])
        anchors = anchors + build_typed_anchors(count)
    if "--semantic-anchors" in sys.argv:
        import json

        idx = sys.argv.index("--semantic-anchors")
        path = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if not path or not os.path.exists(path):
            raise SystemExit(f"--semantic-anchors 文件不存在: {path}")
        with open(path, encoding="utf-8") as fh:
            semantic = json.load(fh)
        if not isinstance(semantic, list) or not semantic:
            raise SystemExit(f"--semantic-anchors 内容为空或非数组: {path}")
        anchors = anchors + semantic
    return anchors


def check_anchors_grounded(anchors):
    """G6 锚点-语料自检（规模验证 §3.4）：每个锚点 targets 至少 1 个存在于已入库简历集合。
    缺失 > 0 即中止——避免「锚点失效但评测静默通过」的假阳性。返回缺失清单。"""
    from django.db.models import QuerySet

    from hr.models import ResumeFile

    known = set(QuerySet(ResumeFile).filter(workspace_id=WORKSPACE).values_list("file_name", flat=True))
    missing = sorted({t for a in anchors for t in a["targets"]} - known)
    if missing:
        print(f"G6 自检失败：{len(missing)} 个目标文件未入库（假阳性风险），前 10 个：{missing[:10]}")
    else:
        print(f"G6 自检通过：{len(anchors)} 锚点，全部 targets 已入库")
    return missing


def run_latency(anchors, service):
    """规模验证 §4.5：随机 N 个锚点逐个计时（meta.elapsed_ms.total，含 rerank），输出 p50/p95；
    附 DB 侧核验：paragraph/embedding 行数与简历份数一致性、简历知识库 hnsw 索引存在性。"""
    import random

    from django.db.models import QuerySet

    from common.db.sql_execute import sql_execute
    from hr.models import ResumeFile
    from knowledge.models import Embedding, Paragraph

    n = 50
    idx = sys.argv.index("--latency")
    if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
        n = int(sys.argv[idx + 1])
    rng = random.Random(42)
    picked = rng.sample(anchors, min(n, len(anchors)))
    llm = service._model_or_none()
    rerank = service._rerank_model_or_none()
    times = []
    for a in picked:
        try:
            result = search_resumes(WORKSPACE, a["q"], top_k=5, mode="auto", hr_role="ADMIN",
                                    user_id=None, llm_model=llm, rerank_model=rerank)
            ms = result["meta"]["elapsed_ms"]["total"]
        except Exception as exc:
            print(f"  [latency-err] {a['q']}: {str(exc)[:80]}")
            continue
        times.append(ms)
        print(f"  {a['q'][:32]:<34} {ms}ms")
    if times:
        times.sort()
        p50 = times[len(times) // 2]
        p95 = times[int(len(times) * 0.95) - 1]
        print(f"延迟 {len(times)} 次: p50={p50}ms p95={p95}ms max={times[-1]}ms")
    resume_qs = QuerySet(ResumeFile).filter(workspace_id=WORKSPACE, document_id__isnull=False)
    n_resume = resume_qs.count()
    n_para = QuerySet(Paragraph).filter(document_id__in=resume_qs.values("document_id")).count()
    n_emb = QuerySet(Embedding).filter(document_id__in=resume_qs.values("document_id")).count()
    print(f"DB 核验: 简历 {n_resume} / 段落 {n_para} / 向量 {n_emb}")
    rows = sql_execute("SELECT indexname FROM pg_indexes WHERE tablename='embedding' AND indexname LIKE %s", ["embedding_hnsw_idx_%"])
    print("hnsw 索引:", [r.get("indexname") for r in rows] or "（无，需触发 create_knowledge_index）")


def main():
    sense_key = os.environ.get("SENSENOVA_API_KEY", "")
    if not sense_key:
        print("SENSENOVA_API_KEY is required")
        return 2
    anchors = load_anchors()
    # G6 自检：锚点 targets 必须已入库（缺失即中止，防假阳性）
    if check_anchors_grounded(anchors):
        return 3
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
    cond_returns = {name: [] for name, _ in modes}  # F8：conditional 锚点返回项（精确率核对用）
    for anchor in anchors:  # F8 修复：--typed 时须遍历扩展后的锚点集（此前主循环用 ANCHORS，typed 汇总段越界崩溃）
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
            # F8：conditional 锚点记录返回候选人（供条件精确率核对）
            if anchor["type"] == "conditional":
                cond_returns.setdefault(name, []).append((anchor, items))
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

    # 结构化基线：Candidate 字段过滤（skills 任一项 / degree >= 词表层级 / years >= / city 归一）
    # F8：此前只处理 skills，years/degree/city 条件被忽略（typed conditional 锚点基线恒 0 无意义）
    from hr.models import Candidate, ResumeFile
    from django.db.models import QuerySet
    from hr.services.query_understand import _DEGREE_LEVELS, degree_words, norm_city
    struct_results = []
    for anchor in anchors:
        cond = anchor["structured"]
        skills = [s.lower() for s in (cond["skills"] or [])]
        cands = list(QuerySet(Candidate).filter(workspace_id=WORKSPACE, status="ACTIVE"))
        hit_names = []
        for c in cands:
            if cond.get("years") is not None and c.years_experience is None:
                continue  # 结构化基线：年限未知视为不匹配（与线上「纳入并标记」口径不同，输出注明）
            if cond.get("years") is not None and c.years_experience < cond["years"]:
                continue
            # 非词表学历（如 MBA）线上预筛不生效（extract_slots 只认词表），基线同样不筛
            if cond.get("degree") is not None and cond["degree"] in _DEGREE_LEVELS:
                if c.highest_degree not in degree_words(_DEGREE_LEVELS[cond["degree"]]):
                    continue
            if cond.get("city") is not None and norm_city(c.current_city or "") != norm_city(cond["city"]):
                continue
            c_skills = [s.lower() for s in (c.skills or [])]
            if skills and not any(s in " ".join(c_skills) for s in skills):
                continue
            rf = QuerySet(ResumeFile).filter(candidate_id=c.id).first()
            if rf:
                hit_names.append(rf.file_name)
        # P2-B 复审修复：恢复逐锚点 struct_results 记录与打印（此前误删导致汇总段除零）
        hit = [t for t in anchor["targets"] if t in hit_names]
        rank = 0
        for idx, fn in enumerate(hit_names[:5], 1):
            if fn in anchor["targets"]:
                rank = idx
                break
        struct_results.append((bool(hit), rank))
        print(f"  结构化基线: {hit_names[:5]} 命中={hit} Top-1={1 if rank == 1 else 0}")
    # 汇总
    print("\n" + "=" * 70)
    print(f"汇总（{len(anchors)} 锚点查询）")
    print("=" * 70)
    for name, _ in modes:
        rows = results[name]
        ok = [r for r in rows if isinstance(r, tuple)]
        if not ok:
            print(f"{name:>12}: 无可用锚点（全部异常或被剔除）")
            continue
        recall5 = sum(1 for r in ok if r[0]) / len(ok)
        recall3 = sum(1 for r in ok if any(v <= 3 for v in r[1].values())) / len(ok)
        top1 = sum(1 for r in ok if any(v == 1 for v in r[1].values())) / len(ok)
        mrr = sum(r[2] for r in ok) / len(ok)
        print(f"{name:>12}: recall@5={recall5:.2f} recall@3={recall3:.2f} Top-1={top1:.2f} MRR={mrr:.3f}")
        if errors[name]:
            print(f"           ⚠ {errors[name]} 个锚点异常被剔除（不计入分母）")
    ok = [r for r in struct_results if isinstance(r, tuple)]
    if not ok:
        print(f"{'结构化基线':>12}: 无可用锚点（跳过）")
    else:
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

    # conditional 条件精确率（F8，规模验证 G3 的验收产出）：
    # 对每个 conditional 锚点返回的 items，核对候选人结构化字段是否满足锚点条件；
    # 精确率 = 满足条件的返回项 / 返回项总数（仅统计有返回的锚点）
    from hr.services.query_understand import _DEGREE_LEVELS, degree_words, norm_city
    print("\nconditional 条件精确率（返回项满足锚点条件的比例；满足条件且被返回 / 返回项数）")
    for name, _ in modes:
        rows = cond_returns[name]
        checked = [(a, items) for a, items in rows if items]
        if not checked:
            continue
        total = sum(len(items) for _, items in checked)
        satisfy = 0
        for a, items in checked:
            cond = a["structured"]
            for it in items:
                c = it.get("candidate")
                if not c:
                    continue
                ok = True
                # NULL 年限按满足计（线上 R2 语义：纳入并标记 years_unknown，非违约）
                if cond.get("years") is not None and c.get("years_experience") is not None and c.get("years_experience") < cond["years"]:
                    ok = False
                # 非词表学历线上预筛不生效，不计违约
                if cond.get("degree") is not None and cond["degree"] in _DEGREE_LEVELS:
                    if c.get("highest_degree") not in degree_words(_DEGREE_LEVELS[cond["degree"]]):
                        ok = False
                if cond.get("city") is not None and norm_city(c.get("current_city") or "") != norm_city(cond["city"]):
                    ok = False
                if ok:
                    satisfy += 1
        print(f"{name:>12}: {satisfy}/{total} = {satisfy / total:.2f}" if total else f"{name:>12}: 无返回项")
    if "--latency" in sys.argv:
        print("\n" + "=" * 70)
        print("延迟测量（§4.5，mode=auto，meta.elapsed_ms.total）")
        print("=" * 70)
        run_latency(anchors, service)
    return 0


if __name__ == "__main__":
    sys.exit(main())
