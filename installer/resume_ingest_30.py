# coding=utf-8
"""
    @project: MaxKB
    @file： resume_ingest_30.py
    @date：2026/8/16
    @desc：量化对比语料入库：testdata/generated/resumes 30 份 txt → 简历知识库（LLM 切片 + 建文档 + 向量化）。
          服务层直调（不依赖 web/celery 常驻）；幂等（按 sha256 跳过已入库）。
          用法：SENSENOVA_API_KEY=... python installer/resume_ingest_30.py
"""
import hashlib
import os
import sys
import time

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

WORKSPACE = "default"
RESUME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata", "generated", "resumes")


def main():
    sense_key = os.environ.get("SENSENOVA_API_KEY", "")
    if not sense_key:
        print("SENSENOVA_API_KEY is required")
        return 2
    from openai import OpenAI

    client = OpenAI(api_key=sense_key, base_url="https://token.sensenova.cn/v1")

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

    files = sorted(f for f in os.listdir(RESUME_DIR) if f.endswith(".txt"))
    done, skipped, failed = 0, 0, 0
    t0 = time.time()
    for name in files:
        path = os.path.join(RESUME_DIR, name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = ResumeFile.objects.filter(workspace_id=WORKSPACE, sha256=sha).first()
        if existing and existing.document_id:
            skipped += 1
            print(f"[skip] {name} 已入库 document_id={existing.document_id}", flush=True)
            continue
        try:
            parsed = parse_resume_text(text)
            with transaction.atomic():
                if existing is None:
                    resume = ResumeFile.objects.create(
                        workspace_id=WORKSPACE, file_name=name, extension="txt",
                        file_path="/tmp/" + name, file_size=len(text.encode("utf-8")),
                        sha256=sha, source_channel="OTHER", status=ResumeStatus.PENDING,
                    )
                    candidate = Candidate.objects.create(
                        workspace_id=WORKSPACE, name=parsed["name"] or name.replace(".txt", ""),
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
            doc_id = index_resume(WORKSPACE, uuid.UUID(int=0), resume, text, chat_fn, stats=stats)
            # 同步向量化（避免起 celery；任务函数内部幂等）
            from knowledge.models import Document, Knowledge
            doc = QuerySet(Document).filter(id=doc_id).first()
            kid = str(doc.knowledge_id) if doc else None
            knowledge = QuerySet(Knowledge).filter(id=kid).first() if kid else None
            model_id = str(knowledge.embedding_model_id) if knowledge else None
            embedding_by_document.run(document_id=doc_id, model_id=model_id)
            done += 1
            print(f"[ok] {name} path={stats.get('path')} doc={doc_id} paragraphs 待查", flush=True)
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {name}: {str(exc)[:200]}", flush=True)
    print(f"\n完成 {done} 份 / 跳过 {skipped} / 失败 {failed} / 耗时 {time.time()-t0:.0f}s")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
