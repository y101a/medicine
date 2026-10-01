"""Turn a persisted assistant answer into faithful, speakable plain text."""

from __future__ import annotations

import html
import re

from app.core.errors import AppError

_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|mailto:)[^)]*\)")
_AUTOLINK = re.compile(r"<(?:https?://|mailto:)[^>]+>")
_BARE_URL = re.compile(r"(?:https?://|www\.)[^\s<>()]+", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_REFERENCE = re.compile(r"\[(?:来源|参考资料|参考)\s*\d+\]")
_HEADING = re.compile(r"^\s*#{1,6}\s+")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)")
_BLOCKQUOTE = re.compile(r"^\s*>+\s?")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_MARKDOWN = re.compile(r"(?<!\\)[*_~`]+")
_MULTISPACE = re.compile(r"[ \t\u00a0]+")
_MULTIPUNCT = re.compile(r"([，。！？；：])\1+")


def prepare_speech_text(content: str, *, max_chars: int) -> str:
    text = _CODE_BLOCK.sub("\n", content)
    text = _MARKDOWN_IMAGE.sub(lambda match: match.group(1), text)
    text = _MARKDOWN_LINK.sub(lambda match: match.group(1), text)
    text = _AUTOLINK.sub("", text)
    text = _BARE_URL.sub("", text)
    text = _HTML_TAG.sub("", text)
    text = html.unescape(text)
    text = _REFERENCE.sub("", text)
    text = _CONTROL.sub("", text)

    spoken_lines: list[str] = []
    for raw_line in text.splitlines():
        if _TABLE_SEPARATOR.fullmatch(raw_line):
            continue
        line = _HEADING.sub("", raw_line)
        line = _BLOCKQUOTE.sub("", line)
        line = _LIST_MARKER.sub("", line)
        line = _INLINE_MARKDOWN.sub("", line)
        line = line.replace("\\_", "_").replace("\\*", "*")
        line = _MULTISPACE.sub(" ", line).strip(" |")
        if not line:
            continue
        line = line.replace(" | ", "，").replace("|", "，")
        if line[-1] not in "。！？；：,.!?;:":
            line += "。"
        spoken_lines.append(line)

    result = _MULTIPUNCT.sub(r"\1", " ".join(spoken_lines)).strip()
    if not result:
        raise AppError(422, "SPEECH_MESSAGE_UNSUPPORTED", "这条内容暂时无法朗读")
    if len(result) > max_chars:
        raise AppError(422, "SPEECH_TEXT_TOO_LONG", "内容较长，请分段朗读")
    return result
