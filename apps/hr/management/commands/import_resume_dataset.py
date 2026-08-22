# coding=utf-8
"""
    @project: MaxKB
    @file： import_resume_dataset.py
    @date：2026/8/17
    @desc: D1 评测语料导入：天池人才简历数据集（数据集/train.json，2000 份脱敏结构化简历）
           渲染为结构化文本 → Candidate + ResumeFile + 简历语义索引。
           结构化字段直接建档（零 LLM 解析）；切片由结构化节构造（零 LLM 切片，
           走 index_resume 的预切片通道）；技能用术语表规则抽取（零 LLM）。
           幂等：sha256 跳过，可断点续跑；同步向量化（不依赖 celery worker）。
           用法：<env> uv run python apps/manage.py import_resume_dataset [--path 数据集/train.json]
                 [--workspace eval-ws] [--limit 300] [--seed 42] [--dry-run] [--manifest logs/xxx.json]
"""
import hashlib
import json
import re
import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import QuerySet

from hr.management.commands.seed_resume_termbase import _EXTRA_TERMS
from hr.models import Candidate, ResumeFile, ResumeStatus
from hr.services.resume_index import index_resume
from hr.services.skill_normalize import normalize_skill
from knowledge.models import Document, Knowledge
from knowledge.task.embedding import embedding_by_document
from users.models import User

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_DEGREE_MAP = {"博士": "博士", "博士学位": "博士", "硕士": "硕士", "硕士学位": "硕士",
               "学士": "本科", "学士学位": "本科", "大专": "大专"}
_YEAR_RANGE_RE = re.compile(r"(\d{4})[./年-]+\d{1,2}[./年-]+(\d{4})")


def _mask_phone(value):
    if not value:
        return ""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 11:
        return digits[:3] + "****" + digits[-4:] if len(digits) >= 7 else "****"
    return digits[:3] + "****" + digits[-4:]


def _years_experience(work_list):
    """从工作经历时间跨度估计年限：取最长跨度年数（跨度为 0 的记录按 1 年计）。"""
    spans = []
    for item in work_list or []:
        raw = str(item.get("工作时间") or "")
        match = _YEAR_RANGE_RE.search(raw)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if 1970 <= start <= end <= 2030:
                spans.append(max(1, end - start))
    return max(spans) if spans else None


def _extract_skills(text):
    """术语表规则抽取技能（零 LLM）：命中即归一化去重。"""
    found = set()
    lowered = text.lower()
    for term in _EXTRA_TERMS:
        if term.lower() in lowered:
            norm = normalize_skill(term)
            found.add(norm or term)
    return sorted(found)


def _render_text(record):
    """结构化简历 → 分节文本（【区块】风格，与切片器结构线索一致）。"""
    lines = []
    lines.append("【基本信息】")
    lines.append("姓名：" + str(record.get("姓名") or "未知"))
    if record.get("出生年月"):
        lines.append("出生年月：" + str(record["出生年月"]))
    degree = _highest_degree(record)
    if degree:
        lines.append("最高学历：" + degree)
    if record.get("籍贯"):
        lines.append("籍贯：" + str(record["籍贯"]))
    for entry in record.get("教育经历") or []:
        lines.append("")
        lines.append("【教育经历】")
        lines.append("毕业时间：" + str(entry.get("毕业时间") or ""))
        lines.append("毕业院校：" + str(entry.get("毕业院校") or ""))
        lines.append("学位：" + str(entry.get("学位") or ""))
    for entry in record.get("工作经历") or []:
        lines.append("")
        lines.append("【工作经历】")
        lines.append("工作时间：" + str(entry.get("工作时间") or ""))
        lines.append("工作单位：" + str(entry.get("工作单位") or ""))
        lines.append("职务：" + str(entry.get("职务") or ""))
        lines.append("工作内容：" + str(entry.get("工作内容") or ""))
    for entry in record.get("项目经历") or []:
        lines.append("")
        lines.append("【项目经历】")
        lines.append("项目时间：" + str(entry.get("项目时间") or ""))
        lines.append("项目名称：" + str(entry.get("项目名称") or ""))
        lines.append("项目责任：" + str(entry.get("项目责任") or ""))
    return "\n".join(lines)


def _highest_degree(record):
    degrees = [str(entry.get("学位") or "") for entry in record.get("教育经历") or []]
    for degree in degrees:
        if degree in _DEGREE_MAP:
            return _DEGREE_MAP[degree]
    return ""


def _build_chunks(record, name):
    """结构化节 → 预切片（每节一个 chunk，超长按 500 字切分；不包含电话等联系方式）。"""
    chunks = []
    degree = _highest_degree(record)
    basic = "姓名：" + str(record.get("姓名") or name)
    if degree:
        basic += "\n最高学历：" + degree
    if record.get("出生年月"):
        basic += "\n出生年月：" + str(record["出生年月"])
    chunks.append({"title": "基本信息", "content": basic})
    for entry in record.get("教育经历") or []:
        content = "\n".join([
            "毕业时间：" + str(entry.get("毕业时间") or ""),
            "毕业院校：" + str(entry.get("毕业院校") or ""),
            "学位：" + str(entry.get("学位") or ""),
        ])
        chunks.append({"title": "教育经历-" + str(entry.get("毕业院校") or "")[:10], "content": content})
    for entry in record.get("工作经历") or []:
        content = "\n".join([
            "工作时间：" + str(entry.get("工作时间") or ""),
            "工作单位：" + str(entry.get("工作单位") or ""),
            "职务：" + str(entry.get("职务") or ""),
            "工作内容：" + str(entry.get("工作内容") or ""),
        ])
        chunks.append({"title": "工作经历-" + str(entry.get("工作单位") or "")[:10], "content": content})
    for entry in record.get("项目经历") or []:
        content = "\n".join([
            "项目时间：" + str(entry.get("项目时间") or ""),
            "项目名称：" + str(entry.get("项目名称") or ""),
            "项目责任：" + str(entry.get("项目责任") or ""),
        ])
        chunks.append({"title": "项目经历-" + str(entry.get("项目名称") or "")[:10], "content": content})
    # 超长 chunk 按句子切分（对齐 50~500 字安全区间）
    trimmed = []
    for chunk in chunks:
        content = chunk["content"]
        if len(content) <= 500:
            trimmed.append(chunk)
            continue
        sentences = re.split(r"(?<=[。；！？\n])", content)
        current = ""
        for sentence in sentences:
            if not sentence.strip():
                continue
            if len(current) + len(sentence) > 500 and current:
                trimmed.append({"title": chunk["title"], "content": current.strip()})
                current = sentence
            else:
                current += sentence
        if current.strip():
            trimmed.append({"title": chunk["title"], "content": current.strip()})
    return trimmed


class Command(BaseCommand):
    help = "导入天池人才简历数据集（结构化）→ 候选人 + 简历语义索引（幂等）"

    def add_arguments(self, parser):
        parser.add_argument("--path", type=str, default="数据集/train.json", help="数据集 JSON 路径")
        parser.add_argument("--workspace", type=str, default="eval-ws", help="目标工作区（默认 eval-ws）")
        parser.add_argument("--limit", type=int, default=None, help="最多导入份数（缺省全量）")
        parser.add_argument("--seed", type=int, default=42, help="抽样种子（可复现）")
        parser.add_argument("--manifest", type=str, default="logs/resume_dataset_manifest.json", help="抽样映射落盘路径")
        parser.add_argument("--dry-run", action="store_true", help="只打印计划不导入")

    def handle(self, *args, **options):
        import os
        import random

        path = options["path"]
        workspace_id = options["workspace"]
        seed = options["seed"]
        limit = options["limit"]
        manifest_path = options["manifest"]
        if not os.path.exists(path):
            self.stderr.write(f"数据集不存在: {path}")
            return
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        records = list(data.items())
        rng = random.Random(seed)
        rng.shuffle(records)
        picked = records[:limit] if limit else records
        self.stdout.write(f"数据集 {len(records)} 条（seed={seed} 抽样 {len(picked)} 条 → workspace={workspace_id}）")
        if options["dry_run"]:
            for key, record in picked[:5]:
                self.stdout.write(f"  计划导入 {key}（{str(record.get('姓名'))}）")
            return

        user = User.objects.order_by("create_time").first()
        if user is None:
            self.stderr.write("users 表无用户，无法创建知识库")
            return
        user_id = user.id
        done = skipped = failed = 0
        manifest = []
        t0 = time.time()
        for key, record in picked:
            name = f"ds_{key}.txt"
            text = _render_text(record)
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            existing = ResumeFile.objects.filter(workspace_id=workspace_id, sha256=sha).first()
            if existing and existing.document_id:
                skipped += 1
                manifest.append({"key": key, "file_name": name, "document_id": str(existing.document_id),
                                 "skipped": True})
                continue
            try:
                degree = _highest_degree(record)
                skills = _extract_skills(text)
                with transaction.atomic():
                    if existing is None:
                        resume = ResumeFile.objects.create(
                            workspace_id=workspace_id, file_name=name, extension="txt",
                            file_path="/tmp/" + name, file_size=len(text.encode("utf-8")),
                            sha256=sha, source_channel="OTHER", status=ResumeStatus.PENDING,
                        )
                        candidate = Candidate.objects.create(
                            workspace_id=workspace_id, name=str(record.get("姓名") or name),
                            phone=_mask_phone(str(record.get("电话") or "")),
                            email=str(record.get("邮箱") or "") or None,
                        )
                        # 0030 后 CandidateSkill 已 DROP，技能仅通过简历原文 RAG 检索
                    else:
                        # 断点续跑：上次失败的残留（无 document_id）复用重建
                        resume = existing
                        candidate = existing.candidate
                    resume.candidate = candidate
                    resume.status = ResumeStatus.SUCCESS
                    resume.save(update_fields=["candidate", "status", "update_time"])
                chunks = _build_chunks(record, name)
                doc_id = index_resume(workspace_id, user_id, resume, text, None, chunks=chunks)
                doc = QuerySet(Document).filter(id=doc_id).first()
                kid = str(doc.knowledge_id) if doc else None
                knowledge_model = QuerySet(Knowledge).filter(id=kid).first() if kid else None
                model_id = str(knowledge_model.embedding_model_id) if knowledge_model else None
                embedding_by_document.run(document_id=doc_id, model_id=model_id)
                done += 1
                manifest.append({
                    "key": key, "file_name": name, "candidate_id": str(candidate.id),
                    "document_id": str(doc_id), "name": candidate.name, "skills": skills,
                    "years_experience": _years_experience(record.get("工作经历")), "highest_degree": degree,
                })
                if done % 25 == 0:
                    self.stdout.write(f"  ...已导入 {done} 条（跳过 {skipped}，失败 {failed}）")
            except Exception as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"[FAIL] {key}: {str(exc)[:200]}"))
        elapsed = time.time() - t0
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump({"workspace": workspace_id, "seed": seed, "imported": done, "skipped": skipped,
                       "failed": failed, "records": manifest}, handle, ensure_ascii=False, indent=1)
        self.stdout.write(self.style.SUCCESS(
            f"完成：导入 {done} / 跳过 {skipped} / 失败 {failed}（耗时 {elapsed:.0f}s）→ manifest {manifest_path}"
        ))
