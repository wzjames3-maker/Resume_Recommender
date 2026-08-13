class Embedder:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = base_url or ""
        self.api_key = api_key or ""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # M1 阶段返回占位向量（1024 维），P2 接入真实 bge-m3 API
        return [[0.1] * 1024 for _ in texts]


embedder = Embedder()