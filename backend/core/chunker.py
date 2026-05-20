"""Text chunking with overlap."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class Chunk:
    text: str
    source: str
    index: int


def chunk_text(text: str, source: str, size: int = 800, overlap: int = 120) -> list[Chunk]:
    text = text.replace("\r\n", "\n")
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[Chunk] = []
    buf = ""
    idx = 0
    for p in paragraphs:
        if len(buf) + len(p) + 1 <= size:
            buf = f"{buf}\n{p}" if buf else p
        else:
            if buf:
                chunks.append(Chunk(text=buf, source=source, index=idx))
                idx += 1
                tail = buf[-overlap:] if overlap > 0 else ""
                buf = f"{tail}\n{p}" if tail else p
            else:
                # single paragraph larger than size — hard-split
                for i in range(0, len(p), size - overlap):
                    chunks.append(Chunk(text=p[i:i+size], source=source, index=idx))
                    idx += 1
                buf = ""
    if buf:
        chunks.append(Chunk(text=buf, source=source, index=idx))
    return chunks
