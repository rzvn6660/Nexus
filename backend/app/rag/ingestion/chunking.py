"""Text chunking algorithms for business context documents."""

import re
import uuid

from app.rag.ingestion.models import ChunkData


class TextChunker:
    """
    Splits business documents into coherent semantic chunks.
    Preserves section headers and context boundaries.
    """

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_markdown(
        self,
        text: str,
        business_domain: str = "general",
        tags: list[str] | None = None,
    ) -> list[ChunkData]:
        """
        Header-aware chunker for Markdown documents.
        Splits text by markdown headers (##, ###, #) while preserving hierarchy.
        """
        lines = text.split("\n")
        sections: list[tuple[str, str]] = []  # (title, body)
        current_title = "Introduction"
        current_lines: list[str] = []

        header_regex = re.compile(r"^(#{1,4})\s+(.+)$")

        for line in lines:
            match = header_regex.match(line)
            if match:
                if current_lines:
                    body = "\n".join(current_lines).strip()
                    if body:
                        sections.append((current_title, body))
                    current_lines = []
                current_title = match.group(2).strip()
            else:
                current_lines.append(line)

        if current_lines:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_title, body))

        # If no markdown headers found, fallback to standard text chunking
        if not sections:
            return self.chunk_text(text, title="Document Content", business_domain=business_domain, tags=tags)

        chunks: list[ChunkData] = []
        chunk_idx = 0

        for title, section_body in sections:
            # If section is small enough, it becomes a single chunk
            if len(section_body) <= self.chunk_size:
                chunks.append(
                    ChunkData(
                        chunk_id=f"chk_{uuid.uuid4().hex[:12]}",
                        chunk_index=chunk_idx,
                        title=title,
                        content=f"## {title}\n{section_body}",
                        business_domain=business_domain,
                        tags=tags or [],
                        metadata_json={"section": title},
                    )
                )
                chunk_idx += 1
            else:
                # Sub-split large sections by paragraphs or size
                sub_chunks = self._split_text_with_overlap(section_body)
                for i, sub_content in enumerate(sub_chunks):
                    chunks.append(
                        ChunkData(
                            chunk_id=f"chk_{uuid.uuid4().hex[:12]}",
                            chunk_index=chunk_idx,
                            title=f"{title} (Part {i+1})",
                            content=f"## {title}\n{sub_content}",
                            business_domain=business_domain,
                            tags=tags or [],
                            metadata_json={"section": title, "part": i + 1},
                        )
                    )
                    chunk_idx += 1

        return chunks

    def chunk_text(
        self,
        text: str,
        title: str | None = None,
        business_domain: str = "general",
        tags: list[str] | None = None,
    ) -> list[ChunkData]:
        """Split plain text or unstructured text by character windows with overlap."""
        sub_chunks = self._split_text_with_overlap(text)
        chunks: list[ChunkData] = []
        for idx, content in enumerate(sub_chunks):
            chunk_title = f"{title} (Section {idx+1})" if title else f"Section {idx+1}"
            chunks.append(
                ChunkData(
                    chunk_id=f"chk_{uuid.uuid4().hex[:12]}",
                    chunk_index=idx,
                    title=chunk_title,
                    content=content,
                    business_domain=business_domain,
                    tags=tags or [],
                    metadata_json={"chunk_index": idx},
                )
            )
        return chunks

    def _split_text_with_overlap(self, text: str) -> list[str]:
        """Split string into overlapping windows respecting paragraph and sentence boundaries."""
        clean_text = text.strip()
        if len(clean_text) <= self.chunk_size:
            return [clean_text] if clean_text else []

        # Split into paragraphs
        paragraphs = clean_text.split("\n\n")
        chunks: list[str] = []
        current_chunk = ""

        for p in paragraphs:
            p_clean = p.strip()
            if not p_clean:
                continue

            if len(current_chunk) + len(p_clean) + 2 <= self.chunk_size:
                current_chunk = f"{current_chunk}\n\n{p_clean}".strip()
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # If paragraph itself exceeds chunk_size, split by sentences or sliding window
                if len(p_clean) > self.chunk_size:
                    for i in range(0, len(p_clean), self.chunk_size - self.chunk_overlap):
                        slice_end = min(i + self.chunk_size, len(p_clean))
                        sub = p_clean[i:slice_end].strip()
                        if sub:
                            chunks.append(sub)
                    current_chunk = ""
                else:
                    current_chunk = p_clean

        if current_chunk:
            chunks.append(current_chunk)

        return chunks
