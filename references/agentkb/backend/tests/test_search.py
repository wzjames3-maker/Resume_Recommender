import uuid

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal
from app.models import (
    EMBEDDING_DIM,
    Chunk,
    Document,
    DocumentStatus,
    KnowledgeBase,
    User,
    Workspace,
)
from app.rag.embedder import embedder
from app.rag.retriever import rrf_merge
from app.services.search_service import hybrid_search


def test_rrf_merge_combines_rankings():
    a = [10, 20, 30]
    b = [30, 40]
    merged = rrf_merge([a, b], k=60)
    # 30 在两路都出现（rank 2 + rank 0），应排名靠前
    assert merged[0] == 30
    assert set(merged) == {10, 20, 30, 40}


def test_rrf_merge_prioritizes_two_way_matches():
    merged = rrf_merge([[1, 2, 3], [3, 1]], k=60)
    # 1 (rank 0 + rank 1) 得分最高，3 (rank 2 + rank 0) 次之，2 仅一路
    assert merged == [1, 3, 2]


@pytest.mark.asyncio
async def test_embedder_placeholder_returns_1024_dim():
    vecs = await embedder.embed(["你好", "世界"])
    assert len(vecs) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vecs)
    assert all(v[0] == 0.1 for v in vecs)


@pytest.mark.asyncio
async def test_hybrid_search_fuses_vector_and_full_text():
    async with SessionLocal() as db:
        user = User(email=f"search{uuid.uuid4().hex[:8]}@t.dev", hashed_password="x", nickname="s")
        db.add(user)
        await db.flush()
        ws = Workspace(name=f"ws{uuid.uuid4().hex[:8]}", owner_id=user.id)
        db.add(ws)
        await db.flush()
        kb = KnowledgeBase(workspace_id=ws.id, name=f"kb{uuid.uuid4().hex[:8]}")
        db.add(kb)
        await db.flush()
        doc = Document(
            knowledge_base_id=kb.id,
            filename="a.txt",
            content_type="text/plain",
            file_size=1,
            storage_key="k",
            status=DocumentStatus.ready,
        )
        db.add(doc)
        await db.flush()

        emb_anchor = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
        emb_mid = [0.0, 1.0] + [0.0] * (EMBEDDING_DIM - 2)
        emb_far = [-1.0] + [0.0] * (EMBEDDING_DIM - 1)
        a = Chunk(document_id=doc.id, content="机器学习基础", position=0, embedding=emb_anchor, metadata_={}, token_count=4)
        b = Chunk(document_id=doc.id, content="深度学习网络", position=1, embedding=emb_mid, metadata_={}, token_count=4)
        c = Chunk(document_id=doc.id, content="机器学习应用", position=2, embedding=emb_far, metadata_={}, token_count=4)
        db.add_all([a, b, c])
        await db.commit()

        try:
            results = await hybrid_search(db, kb.id, emb_anchor, "机器", top_k=3)
            ids = [r.chunk.id for r in results]
            # a 向量+全文双路命中居首；c 双路但向量远；b 仅向量命中
            assert ids == [a.id, c.id, b.id]
        finally:
            await db.execute(text("DELETE FROM knowledge_bases WHERE id = :i"), {"i": kb.id})
            await db.execute(text("DELETE FROM workspaces WHERE id = :i"), {"i": ws.id})
            await db.execute(text("DELETE FROM users WHERE id = :i"), {"i": user.id})
            await db.commit()