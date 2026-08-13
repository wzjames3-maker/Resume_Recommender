def rrf_scores(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def rrf_merge(rankings: list[list[int]], k: int = 60) -> list[int]:
    scores = rrf_scores(rankings, k)
    return sorted(scores, key=lambda d: scores[d], reverse=True)