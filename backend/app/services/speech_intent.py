"""Deterministic, non-billable detection of explicit speech-output requests."""

from __future__ import annotations

import re

from app.schemas.speech import SpeechOutputIntent, SpeechPreset

_NEGATIVE = re.compile(
    r"(?:不要|不用|别|无需|不需要)(?:再|给我|使用|用)?(?:语音|朗读|读出来|播报)|"
    r"(?:只要|仅要|只用|仅用)(?:文字|文本)"
)
_FUNCTION_INQUIRY = re.compile(
    r"(?:你|系统|应用|软件|平台|这个功能).{0,8}"
    r"(?:支持|能否|能不能|可以不可以|会不会|有没有).{0,8}"
    r"(?:语音|朗读|播报)|"
    r"(?:语音输出|朗读功能|播报功能).{0,8}(?:怎么用|如何用|在哪里|是什么)"
)
_QUOTED_OR_HYPOTHETICAL = re.compile(
    r"(?:例如|比如|举例|示例|测试文案|这句话|如果用户|假如用户).{0,20}"
    r"(?:语音回答|语音回复|朗读|读出来|播报|用.+话回答)"
)
_EXPLICIT_ACTION = re.compile(
    r"(?:请|麻烦|帮我|给我)?(?:用|以)?语音(?:来)?(?:回答|回复|输出|播报|朗读)|"
    r"(?:请|麻烦|帮我|给我)(?:把.{0,24})?(?:朗读|读出来|念出来|播报)(?:一下|给我听)?|"
    r"把.{0,24}(?:朗读|读出来|念出来|播报)|"
    r"(?:朗读|播报)(?:一下|给我听)|(?:读出来|念出来)"
)

_DIALECTS: tuple[tuple[re.Pattern[str], SpeechPreset], ...] = (
    (re.compile(r"上海话"), SpeechPreset.SHANGHAI),
    (re.compile(r"(?:粤语|广东话)"), SpeechPreset.CANTONESE),
    (re.compile(r"东北话"), SpeechPreset.NORTHEAST),
    (re.compile(r"重庆话"), SpeechPreset.CHONGQING),
    (re.compile(r"陕西话"), SpeechPreset.SHAANXI),
    (re.compile(r"云南话"), SpeechPreset.YUNNAN),
    (re.compile(r"宁波话"), SpeechPreset.NINGBO),
    (re.compile(r"甘肃话"), SpeechPreset.GANSU),
)
_DIALECT_ACTION = re.compile(r"(?:用|说|讲|以).{0,8}(?:回答|回复|朗读|读|播报|说|讲)")


def speech_output_request(text: str) -> SpeechOutputIntent | None:
    normalized = " ".join(text.split())
    if not normalized or _NEGATIVE.search(normalized):
        return None
    if _FUNCTION_INQUIRY.search(normalized) or _QUOTED_OR_HYPOTHETICAL.search(normalized):
        return None

    preset: SpeechPreset | None = None
    dialect_mentioned = False
    for pattern, candidate in _DIALECTS:
        if pattern.search(normalized):
            dialect_mentioned = True
            preset = candidate
            break
    if preset is None:
        if "男声" in normalized:
            preset = SpeechPreset.MANDARIN_MALE
        elif "女声" in normalized or "普通话" in normalized:
            preset = SpeechPreset.MANDARIN_FEMALE

    explicit = bool(_EXPLICIT_ACTION.search(normalized))
    dialect_request = dialect_mentioned and bool(_DIALECT_ACTION.search(normalized))
    voice_request = preset in {
        SpeechPreset.MANDARIN_FEMALE,
        SpeechPreset.MANDARIN_MALE,
    } and bool(
        re.search(
            r"(?:用|换成|请).{0,6}(?:普通话|男声|女声).{0,8}"
            r"(?:回答|回复|朗读|读|播报)",
            normalized,
        )
    )
    if not (explicit or dialect_request or voice_request):
        return None
    return SpeechOutputIntent(speech_preset=preset)
