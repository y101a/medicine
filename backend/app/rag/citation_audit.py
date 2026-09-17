"""Check source-number correspondence; this does not verify medical claims."""

import re
from typing import Any

SOURCE_MARKER = re.compile(
    r"\[\s*来源\s*([0-9]+)\s*\]|【\s*来源\s*([0-9]+)\s*】"
)
UNNUMBERED_SOURCE_CLAIM = re.compile(
    r"(?:根据|依据|参考)(?:本轮|上述|这些)?(?:检索)?(?:资料|来源|文献)"
    r"|(?:资料|文献|研究)(?:显示|表明|指出)"
)


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
        digits = match.group(1) or match.group(2)
        # Model output is untrusted; avoid converting arbitrarily long integers.
        if len(digits) > 4 or digits.startswith("0"):
            invalid = True
            return "[引用未核实]"
        number = int(digits)
        if number not in available:
            invalid = True
            return "[引用未核实]"
        used.add(number)
        return f"[来源{number}]"

    checked = SOURCE_MARKER.sub(verify, content)
    citations = [item for item in sources if item["reference_number"] in used]
    if invalid:
        checked += (
            "\n\n（回答中有无法对应本轮资料的引用，已标为未核实；"
            "相关表述不能视为有资料支持。）"
        )
    elif sources and not citations and UNNUMBERED_SOURCE_CLAIM.search(checked):
        checked += (
            "\n\n（回答提到了资料或文献依据，但未标注可核验的来源编号；"
            "相关表述不能视为已有资料支持。）"
        )
    return checked, citations
