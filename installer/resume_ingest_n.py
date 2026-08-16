# coding=utf-8
"""
    @project: MaxKB
    @file： resume_ingest_n.py
    @date：2026/8/16
    @desc：规模验证语料入库（计划 §4.2）：label_studio.json（天池 192080，2000 份脱敏 OCR 简历）
          按 seed 抽样 N 份 → 简历知识库（LLM 切片 + 建文档 + 同步向量化）。
          服务层直调（不依赖 web/celery 常驻）；幂等（sha256 跳过，可断点续跑）；
          单份 60s 整体超时 + 重试 1 次；退出码非 0 当失败率 >1% 或存在静默丢失。
          用法：SENSENOVA_API_KEY=... python installer/resume_ingest_n.py [count] [seed] [--workspace ws] [--dry-run]
          输出：/tmp/ingest{count}_manifest.json（抽样映射：idx/file_name/结构化字段，供锚点生成对齐）
"""
import hashlib
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import uuid_utils.compat as uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maxkb.settings")

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402
from django.db.models import QuerySet  # noqa: E402

from hr.models import Candidate, ResumeFile, ResumeStatus  # noqa: E402
from hr.services.resume_index import index_resume  # noqa: E402
from hr.services.resume_parser import parse_resume_text  # noqa: E402
from knowledge.task.embedding import embedding_by_document  # noqa: E402

LABEL_STUDIO_PATH = "/tmp/ds192080/label_studio.json"
_MIN_TEXT_LENGTH = 20  # 与 dataset30 长度过滤一致（计划 §2.1）
_PER_DOC_TIMEOUT = 60  # 单份整体超时（秒，计划 §4.2）
_RETRIES = 1


def _load_corpus():
    """加载语料：返回 [{idx, text}]，idx = 语料原始序号（锚点对齐用）。"""
    with open(LABEL_STUDIO_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    items = []
    for idx, item in enumerate(data):
        text = (item.get("data") or {}).get("text", "")
        if isinstance(text, str) and len(text) >= _MIN_TEXT_LENGTH:
            items.append({"idx": idx, "text": text})
    return items


def _sample(items, count, seed):
    """seed 固定抽样（可复现）：shuffle 原始序号后取前 count 份，命名 ls_{idx:04d}.txt。"""
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


def _process_one(workspace_id, item, chat_fn):
    """单份入库：parse → Candidate+ResumeFile（原子，sha256 幂等）→ index_resume → 同步向量化。
    返回 (name, stats_dict)；已入库跳过时 stats["skipped"]=True。"""
    idx, text = item["idx"], item["text"]
    name = f"ls_{idx:04d}.txt"
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    existing = ResumeFile.objects.filter(workspace_id=workspace_id, sha256=sha).first()
    if existing and existing.document_id:
        return name, {"skipped": True, "document_id": str(existing.document_id)}
    try:
        parsed = parse_resume_text(text)
        with transaction.atomic():
            if existing is None:
                resume = ResumeFile.objects.create(
                    workspace_id=workspace_id, file_name=name, extension="txt",
                    file_path="/tmp/" + name, file_size=len(text.encode("utf-8")),
                    sha256=sha, source_channel="OTHER", status=ResumeStatus.PENDING,
                )
                candidate = Candidate.objects.create(
                    workspace_id=workspace_id, name=parsed["name"] or name.replace(".txt", ""),
                    email=parsed["email"] or None, phone=parsed["phone"],
                    current_city=parsed["current_city"], target_city=parsed["target_city"],
                    highest_degree=parsed["highest_degree"], years_experience=parsed["years_experience"],
                    skills=parsed["skills"], source="OTHER", note=parsed["note"],
                )
                resume.candidate = candidate
                resume.status = ResumeStatus.SUCCESS
                resume.save(update_fields=["candidate", "status", "update_time"])
            else:
                resume = existing
        stats = {}
        started = time.time()
        doc_id = index_resume(workspace_id, uuid.UUID(int=0), resume, text, chat_fn, stats=stats)
        stats["document_id"] = str(doc_id)
        stats["elapsed_s"] = round(time.time() - started, 1)
        # 同步向量化（避免起 celery；任务函数内部幂等）
        from knowledge.models import Document, Knowledge, Paragraph

        doc = QuerySet(Document).filter(id=doc_id).first()
        kid = str(doc.knowledge_id) if doc else None
        knowledge = QuerySet(Knowledge).filter(id=kid).first() if kid else None
        model_id = str(knowledge.embedding_model_id) if knowledge else None
        embedding_by_document.run(document_id=doc_id, model_id=model_id)
        stats["paragraphs"] = QuerySet(Paragraph).filter(document_id=doc_id).count()
        stats["candidate"] = {
            "name": parsed["name"], "years_experience": parsed["years_experience"],
            "highest_degree": parsed["highest_degree"], "current_city": parsed["current_city"],
            "skills": parsed["skills"],
        }
        return name, stats
    except Exception as exc:
        return name, {"error": str(exc)[:300]}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    count = int(args[0]) if args else 200
    seed = int(args[1]) if len(args) > 1 else 42
    workspace_id = "default"
    dry_run = False
    for arg in sys.argv[1:]:
        if arg == "--workspace":
            workspace_id = sys.argv[sys.argv.index(arg) + 1]
        elif arg.startswith("--workspace="):
            workspace_id = arg.split("=", 1)[1]
        elif arg == "--dry-run":
            dry_run = True
    api_key = os.environ.get("SENSENOVA_API_KEY", "")
    if not dry_run and not api_key:
        print("SENSENOVA_API_KEY is required (or use --dry-run)")
        return 2

    corpus = _load_corpus()
    picked = _sample(corpus, count, seed)
    print(f"语料有效 {len(corpus)} 份（>= {_MIN_TEXT_LENGTH} 字），seed={seed} 抽样 {len(picked)} 份 → workspace={workspace_id}", flush=True)
    if dry_run:
        for item in picked[:10]:
            print(f"  计划入库 ls_{item['idx']:04d}.txt（{len(item['text'])} 字）", flush=True)
        print(f"  ...共 {len(picked)} 份（前 10 份预览）", flush=True)
        return 0

    chat_fn = _chat_fn_factory(api_key)
    done = skipped = failed = retried = timed_out = 0
    silent_lost = 0
    manifest = []
    t0 = time.time()
    pool = ThreadPoolExecutor(max_workers=1)

    for item in picked:
        name = f"ls_{item['idx']:04d}.txt"
        last = None
        for attempt in range(_RETRIES + 1):
            try:
                future = pool.submit(_process_one, workspace_id, item, chat_fn)
                result = future.result(timeout=_PER_DOC_TIMEOUT)
            except FutureTimeout:
                timed_out += 1
                last = {"error": f"timeout>{_PER_DOC_TIMEOUT}s"}
                if attempt < _RETRIES:
                    retried += 1
                    print(f"[retry] {name} 超时，重试 {attempt + 1}/1", flush=True)
                    continue
                break
            except Exception as exc:
                last = {"error": f"unexpected: {str(exc)[:200]}"}
                break
            else:
                last = result
                break
        if last is None:
            last = {"error": "unknown"}
        if last.get("skipped"):
            skipped += 1
            print(f"[skip] {name} 已入库 document_id={last.get('document_id')}", flush=True)
            continue
        if last.get("error"):
            failed += 1
            print(f"[FAIL] {name}: {last['error']}", flush=True)
            continue
        done += 1
        if last.get("paragraphs", 0) == 0:
            silent_lost += 1
        print(f"[ok] {name} path={last.get('path')} llm={last.get('llm_calls')} 段落={last.get('paragraphs')} 耗时={last.get('elapsed_s')}s", flush=True)
        manifest.append({
            "file_name": name, "idx": item["idx"],
            "document_id": last.get("document_id"), **(last.get("candidate") or {}),
        })

    elapsed = time.time() - t0
    rate = done / (elapsed / 60) if elapsed > 0 else 0
    fail_rate = failed / (done + failed + skipped) if (done + failed + skipped) else 0
    print(f"\n汇总: 成功 {done} / 跳过 {skipped} / 失败 {failed} / 重试 {retried} / 超时 {timed_out} / 静默丢失 {silent_lost}", flush=True)
    print(f"吞吐 {rate:.1f} 份/分钟（总耗时 {elapsed:.0f}s），失败率 {fail_rate:.1%}", flush=True)
    manifest_path = f"/tmp/ingest{count}_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print(f"抽样映射落盘 {manifest_path}（{len(manifest)} 条，供锚点生成对齐）", flush=True)
    if fail_rate > 0.01 or silent_lost > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
