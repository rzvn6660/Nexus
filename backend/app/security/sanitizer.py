"""Sanitization and input defense utilities for NEXUS."""

import os
import re


def sanitize_filename(filename: str | None) -> str:
    """
    Sanitize an uploaded filename to prevent directory traversal and filesystem attacks.
    Strips directory separators, relative path markers, and dangerous characters.
    """
    if not filename:
        return "unnamed_document.txt"

    # Strip directory path component (handles both UNIX and Windows separators)
    clean_name = os.path.basename(filename.replace("\\", "/"))

    # Remove any null bytes or control characters
    clean_name = re.sub(r"[\x00-\x1f\x7f]", "", clean_name)

    # Restrict to safe characters: alphanumerics, dots, underscores, dashes, spaces
    clean_name = re.sub(r"[^a-zA-Z0-9._\- ]", "_", clean_name)

    # Prevent hidden files or relative paths
    clean_name = clean_name.lstrip(".")

    return clean_name or "document.txt"


def sanitize_query(query: str | None) -> str:
    """
    Sanitize natural language user query string.
    Normalizes whitespace and removes null characters.
    """
    if not query:
        return ""
    # Strip null bytes and non-printable control characters (except common whitespace)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", query)
    # Collapse excessive whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned
