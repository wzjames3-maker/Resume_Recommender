import asyncio

from celery import shared_task
from sqlalchemy import delete

from app.core.database import SessionLocal, engine
from app.models import EMBEDDING_DIM, Chunk, Document, DocumentStatus, KnowledgeBase
from app.rag.splitter import recursive_split


def _extract_text(doc: Document) -> str:
    if doc.content_type in ("text/plain", "text/markdown"):
        with open(doc.storage_key, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    raise NotImplementedError(f"暂不支持解析 {doc.content_type}，该格式解析将在后续版本提供")

async def _run(doc_id: int) -> None:
    async with SessionLocal() as db:
        doc = await db.get(Document, doc_id)
        if doc is None:
            return
        kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
        chunk_size = kb.chunk_size if kb else 512
        chunk_overlap = kb.chunk_overlap if kb else 64
        doc.status = DocumentStatus.processing
        await db.commit()
        try:
            await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            text = _extract_text(doc)
            chunks = recursive_split(text, chunk_size=chunk_size, overlap=chunk_overlap)
            for i, c in enumerate(chunks):
                db.add(Chunk(document_id=doc.id, content=c, position=i, embedding=[0.0] * EMBEDDING_DIM, token_count=len(c)))
            doc.status = DocumentStatus.ready
            doc.chunk_count = len(chunks)
            doc.error_message = None
        except Exception as e:  # noqa: BLE001
            doc.status = DocumentStatus.failed
            doc.error_message = str(e)
        await db.commit()

async def _run_with_fresh_loop(document_id: int) -> None:
    # 连接池可能持有其他事件循环（web 进程 / 上个任务临时 loop）创建的连接，
    # 任务前先释放，任务后再释放，确保不把绑定已关闭临时 loop 的连接留在池中泄漏。
    await engine.dispose()
    try:
        await _run(document_id)
    finally:
        await engine.dispose()

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def parse_document(self, document_id: int) -> None:
    asyncio.run(_run_with_fresh_loop(document_id))