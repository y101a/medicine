"""Health-record context injected into answer generation.

The records are user-stated background, not verified medical history. The rules below
keep them from being used as evidence for a conclusion, and keep red-flag triage
fully independent of them.
"""

HEALTH_CONTEXT_INSTRUCTION = """本轮额外提供该用户此前自行陈述的健康记录。它们是用户自述的背景信息，
不是诊断结论，也不代表已经医生确认；记录可能不准确或已过时。使用规则：
1. 只用于：避免重复询问已知信息、让科普内容更贴合用户关注方向、提示是否需要就医；
2. 不得据记录推断病因、判断病情轻重或给出个体化诊断结论；
3. 不得因为记录中存在某项情况而降低对红旗症状的警惕，紧急分流始终优先；
4. 如与用户本次描述冲突，一律以本次描述为准；
5. 不要主动罗列或复述全部记录，也不要声称已核对用户的病史、病历或检查报告。

用户自述健康记录 JSON：
{health_context}"""


def render_health_context(records_json: str) -> str:
    return HEALTH_CONTEXT_INSTRUCTION.format(health_context=records_json)
