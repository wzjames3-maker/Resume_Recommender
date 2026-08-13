import enum


class BlockKind(str, enum.Enum):
    paragraph = "paragraph"
    table = "table"
    textbox = "textbox"


class Block:
    __slots__ = ("block_id", "content", "kind")

    def __init__(self, kind: BlockKind, content: str, block_id: int):
        self.kind = kind
        self.content = content
        self.block_id = block_id

    def __repr__(self) -> str:
        return f"Block(kind={self.kind.value}, id={self.block_id}, content={self.content[:40]!r})"