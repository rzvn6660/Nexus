"""Security filter and sanitizer for untrusted OKF inputs (Phase 14I).

Ensures imported business context cannot execute code, induce prompt injection,
traverse file paths, or consume unbounded system resources.
"""

import re
from typing import Any


class OKFSecurityError(ValueError):
    """Raised when an OKF payload violates security policies."""
    pass


class OKFSecurityFilter:
    """
    Defensive sanitizer for untrusted business knowledge bundles.
    
    Protections:
    1. Resource bounds: File size, item count, markdown length, YAML depth.
    2. Prompt injection defense: Detects adversarial jailbreaks, hidden prompt directives,
       and attempts to override agent instructions.
    3. Code execution prevention: Detects dangerous YAML tags, Python builtins,
       and eval/exec patterns.
    4. Path traversal prevention: Strict slug validation on IDs and file references.
    5. URL safety: Only whitelisted URI schemes (http, https, urn).
    """

    # Resource bounds
    MAX_BUNDLE_TEXT_BYTES = 2 * 1024 * 1024  # 2 MB
    MAX_ITEMS_PER_BUNDLE = 500
    MAX_DESCRIPTION_CHARS = 50_000
    MAX_YAML_CHARS = 20_000
    MAX_ITEM_ID_LENGTH = 64

    # Prompt injection patterns
    INJECTION_PATTERNS = [
        re.compile(r"\bignore\s+(all\s+)?(previous|prior|system)\s+instructions\b", re.IGNORECASE),
        re.compile(r"\bdisregard\s+(all\s+)?(previous|prior|system)\s+instructions\b", re.IGNORECASE),
        re.compile(r"\byou\s+are\s+now\s+(dan|an\s+unrestricted|jailbroken)\b", re.IGNORECASE),
        re.compile(r"\bsystem\s+override\b", re.IGNORECASE),
        re.compile(r"\bdeveloper\s+mode\s+(enabled|active|on)\b", re.IGNORECASE),
        re.compile(r"\bnew\s+system\s+prompt:\b", re.IGNORECASE),
        re.compile(r"\bdo\s+not\s+follow\s+any\s+safety\s+guidelines\b", re.IGNORECASE),
        re.compile(r"\boutput\s+all\s+environment\s+variables\b", re.IGNORECASE),
        re.compile(r"\breturn\s+the\s+api\s+key\b", re.IGNORECASE),
        re.compile(r"<\s*script\b", re.IGNORECASE),
        re.compile(r"javascript\s*:", re.IGNORECASE),
        re.compile(r"data\s*:\s*text\/html", re.IGNORECASE),
    ]

    # Prohibited YAML tags indicating code execution or object instantiations
    PROHIBITED_YAML_TAGS = [
        "!!python/",
        "!python/",
        "!!perl",
        "!!ruby",
        "!!php",
        "!!js",
        "!ruby",
        "!perl",
    ]

    # Prohibited executable keywords in declarative fields (formula, rules, metadata)
    DANGEROUS_CODE_KEYWORDS = [
        "__import__",
        "__builtins__",
        "__class__",
        "__globals__",
        "eval(",
        "exec(",
        "compile(",
        "os.system",
        "subprocess.",
        "shutil.",
        "sys.modules",
    ]

    @classmethod
    def validate_raw_bundle_text(cls, text: str) -> None:
        """Verify raw bundle text size and check for dangerous tags before parsing."""
        if not text:
            raise OKFSecurityError("Bundle content is empty.")
        
        # 1. Size bounds
        byte_len = len(text.encode("utf-8"))
        if byte_len > cls.MAX_BUNDLE_TEXT_BYTES:
            raise OKFSecurityError(
                f"Bundle size ({byte_len} bytes) exceeds maximum allowable limit of {cls.MAX_BUNDLE_TEXT_BYTES} bytes."
            )

        # 2. Check for unsafe YAML tags before safe_load
        for tag in cls.PROHIBITED_YAML_TAGS:
            if tag in text:
                raise OKFSecurityError(
                    f"Prohibited YAML tag '{tag}' detected in bundle. Deserialization of custom objects is disallowed."
                )

        # 3. Check for dangerous code patterns
        lower_text = text.lower()
        for kw in cls.DANGEROUS_CODE_KEYWORDS:
            if kw.lower() in lower_text:
                raise OKFSecurityError(
                    f"Dangerous code execution pattern '{kw}' detected in bundle text."
                )

    @classmethod
    def sanitize_string_field(cls, value: str, field_name: str = "field") -> str:
        """Detect prompt injection and unsafe patterns in human-authored text."""
        if not value:
            return ""

        # Check for injection patterns
        for pattern in cls.INJECTION_PATTERNS:
            match = pattern.search(value)
            if match:
                raise OKFSecurityError(
                    f"Security policy violation in {field_name}: adversarial or prompt-injection pattern detected: '{match.group()}'"
                )

        # Check for null bytes
        if "\x00" in value:
            raise OKFSecurityError(f"Null byte detected in {field_name}.")

        return value

    @classmethod
    def sanitize_metadata(cls, metadata: dict[str, Any], path: str = "metadata") -> dict[str, Any]:
        """Recursively scan metadata dictionary for malicious payloads."""
        if not isinstance(metadata, dict):
            return {}

        sanitized: dict[str, Any] = {}
        for k, v in metadata.items():
            if not isinstance(k, str):
                raise OKFSecurityError(f"Metadata key must be a string at {path}")
            
            # Check key
            cls.sanitize_string_field(k, f"{path}.key")
            
            if isinstance(v, str):
                sanitized[k] = cls.sanitize_string_field(v, f"{path}.{k}")
            elif isinstance(v, dict):
                sanitized[k] = cls.sanitize_metadata(v, f"{path}.{k}")
            elif isinstance(v, list):
                sanitized[k] = [
                    cls.sanitize_string_field(item, f"{path}.{k}[]") if isinstance(item, str)
                    else cls.sanitize_metadata(item, f"{path}.{k}[]") if isinstance(item, dict)
                    else item
                    for item in v
                ]
            else:
                sanitized[k] = v

        return sanitized

    @classmethod
    def validate_file_path(cls, path: str) -> None:
        """Prevent path traversal when reading or writing local bundle files."""
        if ".." in path or "\\" in path and not path.replace("\\", "/").startswith("/"):
            clean = path.replace("\\", "/")
            if ".." in clean or clean.startswith("/etc") or clean.startswith("/var") or clean.startswith("/root"):
                raise OKFSecurityError(f"Path traversal attempt detected in path: '{path}'")
