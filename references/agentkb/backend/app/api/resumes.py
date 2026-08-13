import hashlib
import json
import logging
import os
import uuid

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import ParseRun, ParseRunStatus, User
from app.services.candidate_access import CandidateAccessError, get_visible_candidate
from app.services.kb_service import ensure_member
from app.services.resume.importers import (
    ResumeImportError,
    parse_csv_bytes,
    parse_json_envelope,
    row_hash,
    write_record_file,
)
from app.services.resume.safety import check_file_signature
from app.tasks.parse_resume import parse_resume

router = APIRouter(prefix="/api/v1", tags=["resumes"])

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {"doc", "docx", "txt", "csv", "json"}
ALLOWED_CHANNELS = {"referral", "job_site", "headhunter", "campus", "other"}
ALLOWED_CONTENT_TYPES = {
    "doc": {"application/msword", "application/octet-stream"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "txt": {"text/plain"},
    "csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
    "json": {"application/json"},
}
MAX_FILES = 100
MAX_FILE_SIZE = 20 * 1024 * 1024
UPLOAD_DIR = os.environ.get("RESUME_UPLOAD_DIR", "/tmp/resume_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _fmt_from_filename(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    if ext == "pdf":
        raise HTTPException(400, "PDF 简历严格拒收，请转换为 doc/docx/txt/csv/json 后上传")
    if ext not in ALLOWED_FORMATS:
        raise HTTPException(400, f"不支持的简历格式: {ext}")
    return ext


async def _create_run(db: AsyncSession, *, workspace_id: int, upload_id: str, source_channel: str,
                      fmt: str, file_path: str, file_size: int, file_hash: str,
                      template_version: str | None = None, referrer: str | None = None) -> ParseRun:
    run = ParseRun(run_id=str(uuid.uuid4()), workspace_id=workspace_id, upload_id=upload_id,
                   source_channel=source_channel, template_version=template_version, referrer=referrer,
                   format=fmt, file_hash=file_hash, file_path=file_path, file_size=file_size,
                   parser_version="0.1.0", status=ParseRunStatus.pending)
    db.add(run)
    return run


async def _read_limited(upload: UploadFile) -> bytes:
    if upload.size is not None and upload.size > MAX_FILE_SIZE:
        raise HTTPException(413, f"文件超过 {MAX_FILE_SIZE} 限制")
    parts, total = [], 0
    while part := await upload.read(1024 * 1024):
        total += len(part)
        if total > MAX_FILE_SIZE:
            raise HTTPException(413, f"文件超过 {MAX_FILE_SIZE} 限制")
        parts.append(part)
    return b"".join(parts)


async def _stream_to_disk(upload: UploadFile, dest: str) -> tuple[str, int]:
    """流式落盘二进制文件，边写边算 sha256；内存占用 O(单文件块)。"""
    digest = hashlib.sha256()
    total = 0
    with open(dest, "wb") as out:  # noqa: ASYNC230
        while part := await upload.read(1024 * 1024):
            total += len(part)
            if total > MAX_FILE_SIZE:
                raise HTTPException(413, f"文件超过 {MAX_FILE_SIZE} 限制")
            digest.update(part)
            out.write(part)
    return digest.hexdigest(), total


async def _find_runs_by_content(db: AsyncSession, ws_id: int, file_hash: str,
                                template_version: str | None, source_channel: str) -> list:
    """内容幂等键（spec §3.4）：workspace + 文件内容 hash + 模板版本 + source_channel。"""
    return list((await db.execute(select(ParseRun).where(
        ParseRun.workspace_id == ws_id,
        ParseRun.file_hash == file_hash,
        ParseRun.template_version == template_version,
        ParseRun.source_channel == source_channel,
    ))).scalars().all())


async def _save_record_run(db: AsyncSession, *, ws_id: int, upload_id: str, source_channel: str,
                           record: dict, template_version: str | None,
                           referrer: str | None) -> tuple[list, str | None]:
    """CSV/JSON 行级记录入 run。内容幂等命中时复用既有 run，不重复创建。"""
    file_hash = row_hash(record)
    existing = await _find_runs_by_content(db, ws_id, file_hash, template_version, source_channel)
    if existing:
        return existing, None
    path, file_size = write_record_file(
        UPLOAD_DIR, ws_id, record,
        {"source_channel": source_channel, "template_version": template_version, "referrer": referrer},
    )
    run = await _create_run(
        db, workspace_id=ws_id, upload_id=upload_id, source_channel=source_channel,
        fmt="json", file_path=path, file_size=file_size, file_hash=file_hash,
        template_version=template_version, referrer=referrer,
    )
    return [run], path


@router.post("/workspaces/{ws_id}/resumes/upload", status_code=202)
async def upload_resumes(ws_id: int, upload_id: str = Form(...), source_channel: str = Form(...),
                          template_version: str | None = Form(None),
                          files: list[UploadFile] = File(...),  # noqa: B008
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    await ensure_member(db, ws_id, user.id)
    if source_channel not in ALLOWED_CHANNELS:
        raise HTTPException(400, f"非法 source_channel: {source_channel}")
    if not upload_id:
        raise HTTPException(400, "缺少 upload_id")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"单次上传不超过 {MAX_FILES} 份")
    # upload_id 幂等：同 (ws, upload_id) 已存在 run 则返回既有 run 列表
    existing = (await db.execute(select(ParseRun).where(
        ParseRun.workspace_id == ws_id, ParseRun.upload_id == upload_id))).scalars().all()
    if existing:
        return {"batch_id": upload_id, "runs": [r.run_id for r in existing], "duplicate": True}

    # 先完整校验并落盘整批，避免第 N 个文件失败时前 N-1 已经 commit 的半批状态。
    # 二进制文件流式落盘（内存 O(单文件)）；CSV/JSON 需完整解析，单文件受 20MB 限制。
    json_csv, prepared, written_paths = [], [], []
    try:
        for f in files:
            fmt = _fmt_from_filename(f.filename or "")
            if (f.content_type or "") not in ALLOWED_CONTENT_TYPES[fmt]:
                raise HTTPException(400, "文件扩展名与 Content-Type 不匹配")
            head = await f.read(8)
            await f.seek(0)
            try:
                check_file_signature(head, fmt)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if fmt in ("json", "csv"):
                content = await _read_limited(f)
                json_csv.append((f.filename or "", fmt, content))
            else:
                storage_key = os.path.join(UPLOAD_DIR, f"{ws_id}-{uuid.uuid4().hex}-{os.path.basename(f.filename or '')}")
                file_hash, file_size = await _stream_to_disk(f, storage_key)
                written_paths.append(storage_key)
                prepared.append((f.filename or "", fmt, storage_key, file_hash, file_size))
    except Exception:
        for p in written_paths:
            os.remove(p)
        raise

    runs, new_runs, row_errors, attempted_hashes = [], [], [], []
    try:
        for _filename, fmt, content in json_csv:
            if fmt == "json":
                try:
                    meta, records, json_errors = parse_json_envelope(json.loads(content))
                except (ResumeImportError, json.JSONDecodeError) as exc:
                    raise HTTPException(400, f"JSON envelope 非法: {exc}") from exc
                if meta["source_channel"] != source_channel:
                    raise HTTPException(400, "multipart source_channel 必须与 JSON envelope 一致")
                row_errors.extend(json_errors)
                for record in records:
                    saved_runs, path = await _save_record_run(
                        db, ws_id=ws_id, upload_id=upload_id, source_channel=source_channel,
                        record=record, template_version=meta.get("template_version"),
                        referrer=meta.get("referrer"),
                    )
                    runs.extend(saved_runs)
                    attempted_hashes.extend(r.file_hash for r in saved_runs)
                    if path:
                        new_runs.extend(saved_runs)
                        written_paths.append(path)
                continue
            if not template_version:
                raise HTTPException(400, "CSV 导入必须提供 template_version")
            try:
                rows, csv_errors = parse_csv_bytes(content)
            except ResumeImportError as exc:
                raise HTTPException(400, str(exc)) from exc
            row_errors.extend(csv_errors)
            for row in rows:
                saved_runs, path = await _save_record_run(
                    db, ws_id=ws_id, upload_id=upload_id, source_channel=source_channel,
                    record=row["data"], template_version=template_version, referrer=None,
                )
                runs.extend(saved_runs)
                attempted_hashes.extend(r.file_hash for r in saved_runs)
                if path:
                    new_runs.extend(saved_runs)
                    written_paths.append(path)
        for _filename, fmt, storage_key, file_hash, file_size in prepared:
            dup = await _find_runs_by_content(db, ws_id, file_hash, template_version, source_channel)
            if dup:
                runs.extend(dup)
                attempted_hashes.append(file_hash)
                os.remove(storage_key)
                written_paths.remove(storage_key)
                continue
            run = await _create_run(db, workspace_id=ws_id, upload_id=upload_id, source_channel=source_channel,
                                    fmt=fmt, file_path=storage_key, file_size=file_size, file_hash=file_hash,
                                    template_version=template_version)
            runs.append(run)
            new_runs.append(run)
            attempted_hashes.append(file_hash)
        await db.commit()
    except IntegrityError:
        # 并发重复上传：内容幂等唯一索引兜底，回滚后复用既有非失败 run（B-6）
        await db.rollback()
        for p in written_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        content_runs = list((await db.execute(select(ParseRun).where(
            ParseRun.workspace_id == ws_id,
            ParseRun.file_hash.in_(attempted_hashes),
            ParseRun.status != ParseRunStatus.failed,
        ))).scalars().all())
        return {"batch_id": upload_id, "runs": [r.run_id for r in content_runs],
                "row_errors": [], "duplicate": True}
    except Exception:
        for p in written_paths:
            os.remove(p)
        raise
    for run in new_runs:
        await db.refresh(run)
        parse_resume.delay(run.run_id)
    return {"batch_id": upload_id, "runs": [run.run_id for run in runs],
            "row_errors": row_errors, "duplicate": not new_runs}


@router.post("/workspaces/{ws_id}/resumes/import", status_code=202)
async def import_resumes(ws_id: int, body: dict, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    await ensure_member(db, ws_id, user.id)
    try:
        meta, records, row_errors = parse_json_envelope(body)
    except ResumeImportError as exc:
        raise HTTPException(400, str(exc)) from exc
    batch_id = meta["upload_id"]
    existing = (await db.execute(select(ParseRun).where(
        ParseRun.workspace_id == ws_id, ParseRun.upload_id == batch_id))).scalars().all()
    if existing:
        return {"batch_id": batch_id, "runs": [run.run_id for run in existing],
                "row_errors": [], "duplicate": True}
    runs, new_runs, written_paths = [], [], []
    try:
        for rec in records:
            saved_runs, path = await _save_record_run(
                db, ws_id=ws_id, upload_id=batch_id, source_channel=meta["source_channel"], record=rec,
                template_version=meta.get("template_version"), referrer=meta.get("referrer"),
            )
            runs.extend(saved_runs)
            if path:
                new_runs.extend(saved_runs)
                written_paths.append(path)
        await db.commit()
    except Exception:
        for p in written_paths:
            os.remove(p)
        raise
    for run in new_runs:
        await db.refresh(run)
        parse_resume.delay(run.run_id)
    return {"batch_id": batch_id, "runs": [run.run_id for run in runs], "row_errors": row_errors}


@router.get("/workspaces/{ws_id}/resumes/runs")
async def list_runs(ws_id: int, page: int = 1, page_size: int = 20,
                    user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    await ensure_member(db, ws_id, user.id)
    page, page_size = max(1, page), max(1, min(page_size, 100))
    total = await db.scalar(select(func.count(ParseRun.id)).where(ParseRun.workspace_id == ws_id))
    rows = await db.execute(select(ParseRun).where(ParseRun.workspace_id == ws_id)
                            .order_by(ParseRun.id.desc()).offset((page - 1) * page_size).limit(page_size))
    items = [{"run_id": r.run_id, "format": r.format, "status": r.status.value,
              "source_channel": r.source_channel, "created_at": r.created_at.isoformat(),
              "error_message": r.error_message} for r in rows.scalars().all()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/resume-runs/{run_id}")
async def get_run(run_id: str, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "资源不存在")
    await ensure_member(db, run.workspace_id, user.id)
    from app.models import ResumeFile, WorkspaceMember
    membership = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == run.workspace_id, WorkspaceMember.user_id == user.id))).scalar_one()
    resume_file = (await db.execute(select(ResumeFile).where(ResumeFile.run_id == run_id))).scalar_one_or_none()
    if resume_file and resume_file.candidate_id:
        try:
            await get_visible_candidate(db, workspace_id=run.workspace_id, candidate_id=resume_file.candidate_id,
                                        role=membership.role.value)
        except CandidateAccessError as exc:
            raise HTTPException(404, str(exc)) from exc
    return {"run_id": run.run_id, "status": run.status.value, "failure_class": run.failure_class.value if run.failure_class else None,
            "retry_count": run.retry_count, "error_message": run.error_message,
            "ir_hash": run.ir_hash, "candidate_hash": run.candidate_hash, "profile_hash": run.profile_hash}


@router.get("/resume-runs/{run_id}/ir")
async def get_run_ir(run_id: str, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    from app.models import ResumeIR
    run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "资源不存在")
    await ensure_member(db, run.workspace_id, user.id)
    ir = (await db.execute(select(ResumeIR).where(ResumeIR.run_id == run_id))).scalar_one_or_none()
    if ir is None:
        raise HTTPException(404, "IR 产物不存在")
    from app.models import ResumeFile, WorkspaceMember
    membership = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == run.workspace_id, WorkspaceMember.user_id == user.id))).scalar_one()
    resume_file = (await db.execute(select(ResumeFile).where(ResumeFile.run_id == run_id))).scalar_one_or_none()
    if resume_file and resume_file.candidate_id:
        try:
            await get_visible_candidate(db, workspace_id=run.workspace_id, candidate_id=resume_file.candidate_id,
                                        role=membership.role.value)
        except CandidateAccessError as exc:
            raise HTTPException(404, str(exc)) from exc
    from app.services.resume.ir_storage import decrypt_resume_ir

    try:
        content = decrypt_resume_ir(ir)
    except (ValueError, InvalidTag):
        logger.error("IR 解密失败", extra={"run_id": run_id})
        raise HTTPException(500, "IR 内容不可读取") from None
    return {"run_id": run_id, "content": content, "valid_chars": ir.valid_chars}


@router.post("/resume-runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: str, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "资源不存在")
    await ensure_member(db, run.workspace_id, user.id)
    from app.models import ResumeFile, WorkspaceMember
    membership = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == run.workspace_id, WorkspaceMember.user_id == user.id))).scalar_one()
    resume_file = (await db.execute(select(ResumeFile).where(ResumeFile.run_id == run_id))).scalar_one_or_none()
    if resume_file and resume_file.candidate_id:
        try:
            await get_visible_candidate(db, workspace_id=run.workspace_id, candidate_id=resume_file.candidate_id,
                                        role=membership.role.value)
        except CandidateAccessError as exc:
            raise HTTPException(404, str(exc)) from exc
    if run.status not in (ParseRunStatus.failed, ParseRunStatus.dead_letter):
        raise HTTPException(409, "仅失败状态的 run 可重试")
    # 人工 retry 生成新 run_id（PRD：人工 retry 生成新的 run_id，不覆盖已发布 revision）
    new_run = ParseRun(run_id=str(uuid.uuid4()), workspace_id=run.workspace_id, upload_id=run.upload_id,
                       source_channel=run.source_channel, template_version=run.template_version, referrer=run.referrer,
                       format=run.format, file_hash=run.file_hash, file_path=run.file_path,
                       file_size=run.file_size, parser_version=run.parser_version, status=ParseRunStatus.pending)
    db.add(new_run)
    await db.commit()
    await db.refresh(new_run)
    parse_resume.delay(new_run.run_id)
    return {"run_id": new_run.run_id, "status": "pending"}
