import re

DIRECT_IDENTIFIER_PATTERNS = (
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\w)"),
    re.compile(r"(?<!\d)\d{15}(?!\d)"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?:姓名[:：]?|我叫)\s*[\u4e00-\u9fff·]{2,10}"),
    re.compile(r"(?:住址|详细地址|家庭地址)[:：]?[^，。；\n]{4,80}"),
)


def redact_direct_identifiers(value: str) -> tuple[str, bool]:
    redacted = False
    for pattern in DIRECT_IDENTIFIER_PATTERNS:
        value, replacements = pattern.subn(" [个人信息已移除] ", value)
        redacted = redacted or replacements > 0
    return value, redacted
