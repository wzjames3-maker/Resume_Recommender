from app.rag.splitter import recursive_split


def test_recursive_split_respects_chunk_size():
    text = "第一段。\n\n第二段内容。\n\n第三段内容继续。"
    chunks = recursive_split(text, chunk_size=10, overlap=2)
    assert all(len(c) <= 12 for c in chunks)
    assert len(chunks) >= 2

def test_short_text_not_split():
    assert recursive_split("你好", chunk_size=512) == ["你好"]

def test_empty_text_returns_empty_list():
    assert recursive_split("", chunk_size=512) == []

def test_chunks_keep_original_text_approximately():
    text = ("第一段内容。\n\n第二段内容。\n\n第三段内容继续。\n\n第四段内容最后。")
    joined = "".join(recursive_split(text, chunk_size=10, overlap=2))
    assert "第一段内容" in joined
    assert "第四段内容最后" in joined

def test_overlap_shared_between_consecutive_chunks():
    text = "a" * 60
    chunks = recursive_split(text, chunk_size=10, overlap=2)
    assert len(chunks) >= 2
    for i in range(1, len(chunks)):
        assert chunks[i].startswith(chunks[i - 1][-2:])