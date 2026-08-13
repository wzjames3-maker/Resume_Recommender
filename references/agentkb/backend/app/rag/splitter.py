def recursive_split(text: str, chunk_size: int = 512, overlap: int = 64, separators: tuple[str, ...] = ("\n\n", "\n", "。", " ")) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text else []
    if not separators:
        step = max(chunk_size - overlap, 1)
        return [text[i:i + chunk_size] for i in range(0, len(text), step)]
    sep, rest = separators[0], separators[1:]
    pieces = text.split(sep)
    chunks, buf = [], ""
    for i, part in enumerate(pieces):
        piece = part + sep if i < len(pieces) - 1 else part
        if len(piece) > chunk_size:
            if buf:
                chunks.append(buf); buf = ""
            chunks.extend(recursive_split(piece, chunk_size, overlap, rest))
        elif len(buf) + len(piece) <= chunk_size:
            buf += piece
        else:
            chunks.append(buf); buf = piece
    if buf:
        chunks.append(buf)
    for i in range(1, len(chunks)):
        chunks[i] = chunks[i - 1][-overlap:] + chunks[i]
    return chunks