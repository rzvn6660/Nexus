"""Adversarial prompt injection defense and guardrails for NEXUS NLU."""

import re

# Common prompt injection, jailbreak, and system instruction override patterns
INJECTION_PATTERNS = [
    r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|prompts|rules|commands)\b",
    r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|rules)\b",
    r"(?i)\byou\s+are\s+now\s+(?:dan|developer\s+mode|unrestricted|god\s+mode|jailbroken)\b",
    r"(?i)\bdo\s+anything\s+now\b",
    r"(?i)\bsystem\s+prompt\s*(?:override|leak|reveal|print)\b",
    r"(?i)\bprint\s+(?:your\s+)?system\s+(?:prompt|instructions)\b",
    r"(?i)\bshow\s+(?:me\s+)?(?:your\s+)?(?:system\s+prompt|raw\s+instructions)\b",
    r"(?i)\bwhat\s+(?:are|is)\s+your\s+system\s+(?:prompt|instructions)\b",
    r"(?i)\bdrop\s+database\b",
    r"(?i)\bdrop\s+table\b",
    r"(?i)\btruncate\s+table\b",
]

COMPILED_PATTERNS = [re.compile(p) for p in INJECTION_PATTERNS]


def detect_prompt_injection(text: str) -> tuple[bool, str | None]:
    """
    Scan query for common adversarial prompt injection and system override attempts.
    
    Returns:
        (is_injection, reason)
    """
    if not text:
        return False, None

    for pattern in COMPILED_PATTERNS:
        match = pattern.search(text)
        if match:
            return True, f"Adversarial instruction pattern detected: '{match.group(0)}'"

    return False, None
