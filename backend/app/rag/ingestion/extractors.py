"""Document text extractors and security sanitizers for NEXUS RAG ingestion."""

import io
import os
import re
from typing import ClassVar

from app.core.config import settings


def sanitize_filename(filename: str) -> str:
    """
    Sanitize uploaded filename to defend against path traversal and dangerous characters.
    Strips directory separators, null bytes, and non-printable characters.
    """
    # Remove path components
    basename = os.path.basename(filename)
    # Remove null bytes
    basename = basename.replace("\x00", "")
    # Remove non-alphanumeric except safe punctuation
    clean = re.sub(r"[^\w\.\-\_ ]", "", basename)
    # Collapse multiple dots/slashes
    clean = re.sub(r"\.{2,}", ".", clean)
    clean = clean.strip(". ")
    if not clean:
        clean = "document"
    return clean


class DocumentExtractor:
    """Safe extractor transforming raw file bytes into normalized text strings."""

    SUPPORTED_EXTENSIONS: ClassVar[set[str]] = {".md", ".txt", ".pdf"}

    @classmethod
    def extract_text_and_type(cls, file_bytes: bytes, filename: str) -> tuple[str, str]:
        """
        Validate file constraints, detect document type, and extract normalized text.
        
        Raises:
            ValueError: If file size exceeds limit or format is unsupported/corrupted.
        """
        # 1. Enforce size limit
        if len(file_bytes) > settings.MAX_DOCUMENT_SIZE_BYTES:
            max_mb = settings.MAX_DOCUMENT_SIZE_BYTES / (1024 * 1024)
            raise ValueError(
                f"File size ({len(file_bytes)} bytes) exceeds the maximum limit of {max_mb:.1f}MB."
            )

        # 2. Check extension
        sanitized = sanitize_filename(filename)
        _, ext = os.path.splitext(sanitized.lower())
        if ext not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported document format '{ext}'. Allowed extensions: {', '.join(cls.SUPPORTED_EXTENSIONS)}"
            )

        # 3. Extract according to extension
        if ext == ".md":
            text = cls._extract_text(file_bytes)
            return text, "markdown"
        elif ext == ".txt":
            text = cls._extract_text(file_bytes)
            return text, "txt"
        elif ext == ".pdf":
            text = cls._extract_pdf(file_bytes)
            return text, "pdf"
        else:
            raise ValueError(f"Unhandled file extension: {ext}")

    @staticmethod
    def _extract_text(file_bytes: bytes) -> str:
        """Decode raw text bytes with UTF-8 and fallback encodings, cleaning control characters."""
        try:
            raw = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                raw = file_bytes.decode("latin-1")
            except (UnicodeDecodeError, ValueError) as e:
                raise ValueError(f"Failed to decode text document encoding: {e}")

        # Strip null bytes and normalize newlines
        clean = raw.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        return clean.strip()

    @staticmethod
    def _extract_pdf(file_bytes: bytes) -> str:
        """Extract text from PDF pages using pypdf."""
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF documents are not supported.")

            pages_text = []
            for i, page in enumerate(reader.pages):
                page_content = page.extract_text() or ""
                clean_page = page_content.strip()
                if clean_page:
                    pages_text.append(f"## Page {i + 1}\n{clean_page}")

            full_text = "\n\n".join(pages_text)
            if not full_text.strip():
                raise ValueError("PDF document contains no extractable text.")

            return full_text
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"Corrupted or invalid PDF document: {e}")
