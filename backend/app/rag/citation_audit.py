"""Check source-number correspondence; this does not verify medical claims."""

import re
from typing import Any

SOURCE_MARKER = re.compile(r"\[来源([0-9]+)\]")


def audit_answer_citations(
    content: str, sources: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Keep only cited evidence and remove references to absent source numbers.

    The model's evidence is numbered by retrieval *chunk*, not by URL. Keep
    those numbers intact even when multiple chunks share the same document.
    """
    available = {item["reference_number"]: item for item in sources}
    used: set[int] = set()
    invalid = False

    def verify(match: re.Match[str]) -> str:
        nonlocal invalid
        digits = match.group(1)
        # Model output is untrusted; avoid converting arbitrarily long integers.
        if len(digits) > 4 or digits.startswith("0"):
            invalid = True
            return "[引用未核实]"
        number = int(digits)
        if number not in available:
            invalid = True
            return "[引用未核实]"
        used.add(number)
        return match.group(0)

    checked = SOURCE_MARKER.sub(verify, content)
    citations = [item for item in sources if item["reference_number"] in used]
    if invalid:
        checked += (
            "\n\n（回答中有无法对应本轮资料的引用，已标为未核实；"
            "相关表述不能视为有资料支持。）"
        )
    elif sources and not citations:
        checked += "\n\n（本轮回答未标注来源，无法核对回答与检索资料的对应关系。）"
    return checked, citations
