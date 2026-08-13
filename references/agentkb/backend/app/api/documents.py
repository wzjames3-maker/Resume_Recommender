import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Chunk, Document, DocumentStatus, User
from app.services.kb_service import (
    get_doc_for_admin,
    get_doc_for_member,
    get_kb_for_admin,
    get_kb_for_member,
    remove_storage_file,
)
from app.tasks.parse_document import parse_document

router = APIRouter(prefix="/api/v1", tags=["documents"])

ALLOWED = {
    "application/pdf": ".pdf",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
MAX_SIZE = 50 * 1024 * 1024
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/tmp/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

_VALID_STATUSES = {s.value for s in DocumentStatus}

def _check_upload(filename: str, content_type: str, head: bytes) -> None:
    ext = os.path.splitext(filename or "")[1].lower()
    if content_type not in ALLOWED:
        raise HTTPException(400, f"不支持的文件类型: {content_type}")
    if not ext or ext != ALLOWED[content_type]:
        raise HTTPException(400, "文件扩展名与 Content-Type 不匹配")
    if content_type == "application/pdf" and not head.startswith(b"%PDF"):
        raise HTTPException(400, "文件内容与 PDF 格式不匹配")
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" and not head.startswith(b"PK\x03\x04"):
        raise HTTPException(400, "文件内容与 DOCX 格式不匹配")
    if content_type in ("text/plain", "text/markdown") and b"\x00" in head:
        raise HTTPException(400, "文本文件包含非文本内容")

async def _read_limited(file: UploadFile, max_size: int) -> bytes:
    if file.size is not None and file.size > max_size:
        raise HTTPException(413, f"文件超过 {max_size} 字节限制")
    parts: list[bytes] = []
    total = 0
    while True:
        part = await file.read(1024 * 1024)
        if not part:
            break
        total += len(part)
        if total > max_size:
            raise HTTPException(413, f"文件超过 {max_size} 字节限制")
        parts.append(part)
    return b"".join(parts)

@router.post("/knowledge-bases/{kb_id}/documents", status_code=202)
async def upload_document(kb_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):  # noqa: B008
    kb = await get_kb_for_admin(db, kb_id, user)
    head = await file.read(8)
    await file.seek(0)
    _check_upload(file.filename or "", file.content_type or "", head)
    content = await _read_limited(file, MAX_SIZE)
    safe_name = os.path.basename(file.filename or "")
    storage_key = os.path.join(UPLOAD_DIR, f"{kb_id}-{uuid.uuid4().hex}-{safe_name}")
    with open(storage_key, "wb") as f:  # noqa: ASYNC230
        f.write(content)
    doc = Document(knowledge_base_id=kb.id, filename=file.filename, content_type=file.content_type, file_size=len(content), storage_key=storage_key, status=DocumentStatus.pending)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    parse_document.delay(doc.id)
    return {"document_id": doc.id, "status": "pending"}

@router.get("/knowledge-bases/{kb_id}/documents")
async def list_documents(kb_id: int, page: int = 1, page_size: int = 20, status: str | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await get_kb_for_member(db, kb_id, user)
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    filters = [Document.knowledge_base_id == kb.id]
    if status is not None:
        if status not in _VALID_STATUSES:
            raise HTTPException(400, f"非法状态: {status}")
        filters.append(Document.status == DocumentStatus(status))
    total = await db.scalar(select(func.count(Document.id)).where(*filters))
    rows = await db.execute(
        select(Document).where(*filters).order_by(Document.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = [
        {
            "id": d.id,
            "knowledge_base_id": d.knowledge_base_id,
            "filename": d.filename,
            "file_size": d.file_size,
            "status": d.status.value,
            "chunk_count": d.chunk_count,
            "created_at": d.created_at,
        }
        for d in rows.scalars().all()
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}

@router.get("/documents/{doc_id}")
async def get_document(doc_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await get_doc_for_member(db, doc_id, user)
    return {
        "id": doc.id,
        "knowledge_base_id": doc.knowledge_base_id,
        "filename": doc.filename,
        "file_size": doc.file_size,
        "status": doc.status.value,
        "chunk_count": doc.chunk_count,
        "error_message": doc.error_message,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }

@router.get("/documents/{doc_id}/chunks")
async def list_chunks(doc_id: int, page: int = 1, page_size: int = 20, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await get_doc_for_member(db, doc_id, user)
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = await db.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == doc.id))
    rows = await db.execute(
        select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.position).offset((page - 1) * page_size).limit(page_size)
    )
    items = [
        {"id": ch.id, "document_id": ch.document_id, "content": ch.content, "token_count": ch.token_count, "position": ch.position, "created_at": ch.created_at}
        for ch in rows.scalars().all()
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}

@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await get_doc_for_admin(db, doc_id, user)
    if doc.status == DocumentStatus.processing:
        raise HTTPException(409, "文档正在解析中，请稍后再试")
    storage_key = doc.storage_key
    await db.delete(doc)
    await db.commit()
    remove_storage_file(storage_key)

@router.post("/documents/{doc_id}/retry", status_code=202)
async def retry_document(doc_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await get_doc_for_admin(db, doc_id, user)
    if doc.status != DocumentStatus.failed:
        raise HTTPException(409, "仅 failed 状态的文档可重试")
    doc.status = DocumentStatus.processing
    doc.error_message = None
    await db.commit()
    parse_document.delay(doc.id)
    return {"document_id": doc.id, "status": "processing"}