import json

import pytest

from app.ai.follow_up import FOLLOW_UP_PREFIX, parse_follow_up
from app.core.errors import AppError


def test_invalid_follow_up_control_is_rejected():
    content = FOLLOW_UP_PREFIX + "\n" + json.dumps(
        {
            "intro": "请补充以下信息",
            "questions": [
                {
                    "id": "location",
                    "label": "症状位置在哪里？",
                    "type": "dropdown",
                    "required": True,
                    "options": [],
                },
                {
                    "id": "duration",
                    "label": "症状持续多久？",
                    "type": "text",
                    "required": True,
                    "options": [],
                },
            ],
        },
        ensure_ascii=False,
    )
    with pytest.raises(AppError) as raised:
        parse_follow_up(content, strict=True)
    assert raised.value.code == "AI_INVALID_STRUCTURED_RESPONSE"


def test_follow_up_accepts_preface_and_markdown_escaped_underscores():
    content = r'''先提供一段普通说明。
[[FOLLOW\_UP\_CARD]]
{"intro":"请补充信息","questions":[{"id":"pain\_location","label":"疼痛位置？","type":"single\_choice","required":true,"options":[{"value":"one\_side","label":"一侧"},{"value":"both\_sides","label":"双侧"}]},{"id":"duration","label":"持续多久？","type":"text","required":true,"options":[]}]}'''

    card = parse_follow_up(content, strict=True)

    assert card is not None
    assert card.questions[0].id == "pain_location"
    assert card.questions[0].type == "single_choice"
    assert card.questions[0].options[0].value == "one_side"
