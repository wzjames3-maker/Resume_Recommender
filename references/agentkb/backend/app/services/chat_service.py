from app.services.search_service import SearchHit


async def build_answer(query: str, hits: list[SearchHit]) -> str:
    # M1 阶段：拼接检索片段返回，不调用真实 LLM（P2 接 DeepSeek）
    if not hits:
        return "未在知识库中找到相关内容。"
    return "根据知识库内容：" + "；".join(h.chunk.content[:80] for h in hits[:3])