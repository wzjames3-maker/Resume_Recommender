from dataclasses import dataclass

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EMBEDDING_DIM, Chunk
from app.rag.retriever import rrf_merge, rrf_scores


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


async def hybrid_search(db: AsyncSession, kb_id: int, query_embedding: list[float], query_text: str, top_k: int = 10) -> list[SearchHit]:
    # 向量检索（pgvector 余弦距离）
    vec_stmt = text(
        "SELECT c.id FROM chunks c JOIN documents d ON c.document_id = d.id "
        "JOIN knowledge_bases k ON d.knowledge_base_id = k.id "
        "WHERE k.id = :kb_id AND d.status = 'ready' ORDER BY c.embedding <=> :q LIMIT :n"
    ).bindparams(bindparam("q", type_=Vector(EMBEDDING_DIM)))
    vec_rows = await db.execute(vec_stmt, {"kb_id": kb_id, "q": query_embedding, "n": top_k * 2})
    vec_ids = [r[0] for r in vec_rows.all()]
    # 全文检索（ILIKE 简化实现，中文分词在集成阶段替换）
    full_stmt = text(
        "SELECT c.id FROM chunks c JOIN documents d ON c.document_id = d.id "
        "JOIN knowledge_bases k ON d.knowledge_base_id = k.id "
        "WHERE k.id = :kb_id AND d.status = 'ready' AND c.content ILIKE :q ORDER BY c.id LIMIT :n"
    )
    full_rows = await db.execute(full_stmt, {"kb_id": kb_id, "q": f"%{query_text}%", "n": top_k * 2})
    full_ids = [r[0] for r in full_rows.all()]

    rankings = [vec_ids, full_ids]
    scores = rrf_scores(rankings)
    merged = rrf_merge(rankings)[:top_k]
    if not merged:
        return []
    max_score = max((scores[i] for i in merged), default=0.0)
    rows = await db.execute(select(Chunk).where(Chunk.id.in_(merged)))
    by_id = {c.id: c for c in rows.scalars().all()}
    hits = []
    for chunk_id in merged:
        if chunk_id in by_id:
            score = (scores[chunk_id] / max_score) if max_score > 0 else 0.0
            hits.append(SearchHit(chunk=by_id[chunk_id], score=round(score, 4)))
    return hits