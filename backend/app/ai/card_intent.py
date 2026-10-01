"""Conservative, local recognition of explicit text-card requests."""

import re
import unicodedata


def requests_pathology_card(text: str) -> bool:
    text = unicodedata.normalize("NFKC", text).strip()
    if re.search(r"不要|不用|别|不需要|取消|如何|怎么|能否|能不能|可以吗|吗[？?]?$", text):
        return False
    if re.search(r"银行卡|信用卡|贺卡|名片|单词卡|PPT|Word|配图|图片", text, re.I):
        return False
    return bool(
        re.search(r"(?:生成|制作|做|整理|总结|转成|变成).{0,40}(?:科普卡|卡片)", text)
        or re.search(r"(?:用|以|按)卡片(?:形式|格式).{0,20}(?:介绍|解释|讲解|说明)", text)
    )


def requests_previous_card(text: str) -> bool:
    """Do not silently substitute a previous health topic for a new unknown topic."""
    return bool(re.fullmatch(
        r"(?:请|帮我|请帮我)?(?:把)?(?:刚才的回答|上面的回答|上一条回答|这个|它)?"
        r"(?:生成|制作|做|整理成|总结成|转成|变成)(?:一张|一个)?"
        r"(?:病理科普卡片|科普卡片|卡片|科普卡)[。！!\s]*",
        unicodedata.normalize("NFKC", text).strip(),
    ))
