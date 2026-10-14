"""Adversarial prompt injection defense and guardrails for NEXUS NLU."""

import re

# Common prompt injection, jailbreak, system instruction override, and exfiltration patterns
INJECTION_PATTERNS = [
    r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|prompts|rules|commands)\b",
    r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|rules)\b",
    r"(?i)\bforget\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|rules|prompts)\b",
    r"(?i)\byou\s+are\s+now\s+(?:dan|developer\s+mode|unrestricted|god\s+mode|jailbroken)\b",
    r"(?i)\bdo\s+anything\s+now\b",
    r"(?i)\b(?:new|override)\s+system\s+(?:instructions?|prompt|rules?)\b",
    r"(?i)\bsystem\s+prompt\s*(?:override|leak|reveal|print)\b",
    r"(?i)\bprint\s+(?:your\s+)?system\s+(?:prompt|instructions)\b",
    r"(?i)\bshow\s+(?:me\s+)?(?:your\s+)?(?:system\s+prompt|raw\s+instructions)\b",
    r"(?i)\bwhat\s+(?:are|is)\s+your\s+system\s+(?:prompt|instructions)\b",
    r"(?i)\[\s*system\s+instructions?\s*\]",
    r"(?i)\b(?:reveal|leak|exfiltrate|dump|print)\s+(?:all\s+)?(?:api[_\-\s]?keys?|tokens?|secrets?|passwords?|database|data|rows|tables?)\b",
    r"(?i)\b(?:switch|change)\s+to\s+(?:another\s+)?(?:tenant|business|organization)\b",
    r"(?i)\bselect\s+\*\s+from\s+(?:users|passwords|credentials|tenants|accounts)\b",
    r"(?i)\broot[\s_]+admin\b|\bsecurity_bypass\b|\badmin_mode\b",
    r"(?i)\bdrop\s+database\b",
    r"(?i)\bdrop\s+table\b",
    r"(?i)\btruncate\s+table\b",
]

COMPILED_PATTERNS = [re.compile(p) for p in INJECTION_PATTERNS]


def detect_prompt_injection(text: str) -> tuple[bool, str | None]:
    """
    Scan query or text for common adversarial prompt injection and system override attempts.
    
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


def scan_untrusted_context(text: str) -> tuple[bool, str | None]:
    """
    Scan untrusted retrieved context (e.g. RAG documents, catalog descriptions)
    for embedded indirect prompt injection vectors before injecting into prompts.
    
    Returns:
        (is_malicious, reason)
    """
    if not text:
        return False, None

    return detect_prompt_injection(text)

