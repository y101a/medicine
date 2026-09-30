"""Decide whether one user message states a personal health fact worth extracting.

This is deliberately **not** the RAG retrieval gate (``app.ai.graph.retrieval_gate``).
That gate answers "should this question retrieve medical knowledge?", and it rejects
personal self-descriptions that carry no known symptom keyword -- 「我最近总口渴」(no
vocabulary entry for 口渴) and 「最近感觉身体状态不错：脸上红红的」 (no 红肿/皮疹 match)
both came back as ``non_medical_content``. Reusing it as the extraction gate therefore
made the product silently store nothing from real conversations, even though the
collection switch was on.

This module answers a different question: *did the user state something about their own
body or health that they would expect the product to remember?* It is a recall-oriented
screen with two consequences that shape the design:

* a wrong "yes" costs one extra extraction call, whose output is still filtered by the
  structured extractor prompt **and** ``app.ai.health_extract.is_safe_fact``;
* a wrong "no" silently loses a fact the user stated, which is the bug being fixed here.

So the vocabulary is intentionally broad (body parts, sensation words, medication,
allergy, lifestyle, self-measurement, care seeking, long-term conditions) and the
rejection rules are about *framing* rather than about a whitelist of symptoms: a message
must look like the user's own report, not like a greeting, a general knowledge question,
a question about the product itself, or a report about somebody else.

Known limits (kept honest on purpose): matching is Chinese-first, so English self-reports
are not recognised; the screen cannot tell a family history phrase inside a mostly
first-person message apart from the user's own statement (the extractor prompt is told to
drop third-party facts); and nothing here reads ``retrieval_gate_reason`` or
``Message.is_medical_content``.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

HealthEligibilityReason = Literal[
    "empty",
    "social-only",
    "identity-question",
    "product-capability",
    "off-topic-request",
    "record-query",
    "no-health-content",
    "general-knowledge-question",
    "third-party",
    "no-personal-framing",
    "self-disclosure",
]


@dataclass(frozen=True, slots=True)
class HealthEligibilityDecision:
    eligible: bool
    reason: HealthEligibilityReason


# 只有寒暄、致谢、应答，没有别的内容。整条匹配，避免把「你好，我最近总口渴」判成闲聊。
SOCIAL_ONLY = re.compile(
    r"^(?:你好|您好|哈喽|嗨|hi|hello|早上好|上午好|下午好|晚上好|晚安|谢谢|感谢|多谢|"
    r"再见|拜拜|好的|好|嗯|哦|在吗|在么|收到|明白)[呀啊哦哈呢吧啦了！!。，,~～\s]*$",
    re.IGNORECASE,
)

# 模型身份：问“你是谁/什么模型”，不是用户自述。
IDENTITY_QUESTION = re.compile(
    r"(?:你是谁|你叫什么|什么模型|哪个模型|哪家的模型|介绍一下你自己|你会什么|你能做什么)"
)

# 与本产品、与健康都不相干的通用请求。
OFF_TOPIC_REQUEST = re.compile(
    r"(?:讲个笑话|写.{0,4}代码|写作文|写文章|翻译一下|今天天气|现在几点|吃饭了吗)"
)

# 关于**产品本身**（是否记录/保存/自动更新、隐私、采集开关、记录管理、账号操作）的提问。
PRODUCT_CAPABILITY = re.compile(
    r"(?:自动更新|自动记录|自动保存|自动提取|自动抽取|自动同步|定期更新|定时更新|"
    r"会保存|会记录|会提取|会抽取|会更新|会不会记录|会不会保存|你能记录|你能保存|"
    r"能记住|记住我|是否自动|健康记录|我的记录|采集|隐私|数据安全|保存多久|"
    r"删除记录|导出记录|关闭采集|开启采集|设置里|这个系统的功能|如何使用这个|"
    r"怎么用这个|怎么登录|怎么注册|切换模型|上传头像|修改头像)"
)

# 在问“我已经存了什么”，而不是在陈述事实。
RECORD_QUERY = re.compile(
    r"(?:你记得我|你还记得我|你知道我|我之前说过吗|我之前说过什么|我记录里|我的记录里|"
    r"记录里有没有|我有哪些记录|帮我看看记录|查看我的记录)"
)

GENERAL_KNOWLEDGE = re.compile(
    r"(?:什么是|啥是|是什么|有哪些|有什么|怎么回事|什么原因|为什么会|为什么|"
    r"怎么治|怎么办|如何治|如何预防|怎么预防|能治好吗|能治吗|严重吗|要紧吗|"
    r"会传染吗|传染吗|吃什么药|用什么药|需要吃什么|挂什么科|挂哪个科|要不要紧|"
    r"危险吗|多久能好|怎么检查|有什么症状|会遗传吗|能不能吃|可不可以吃|适合吃吗|"
    r"有用吗|有效吗|区别是什么|分为几类|哪些类型|要注意什么|需要忌口|忌口)"
)

# 他人（家属/朋友/同事）的情况，不是用户本人的自述。
THIRD_PARTY = re.compile(
    r"(?:我朋友|我的朋友|我妈|我妈妈|我母亲|我爸|我爸爸|我父亲|我哥|我哥哥|我姐|我姐姐|"
    r"我弟|我弟弟|我妹|我妹妹|我儿子|我女儿|我孩子|我娃|我老公|我老婆|我媳妇|我丈夫|"
    r"我妻子|我对象|我男朋友|我女朋友|我同事|我同学|我邻居|我家人|我家里|我们家|"
    r"我爷爷|我奶奶|我外公|我外婆|我姥姥|我姥爷|我叔叔|我姑姑|我舅舅|我姨|"
    r"我侄子|我外甥|家人|家里人|朋友|同事|邻居|患者|病人|孩子他妈|孩子他爸)"
)

# “我的健康记录/我的信息”这类是账号与记录的所有格，不是用户的身体事实；
# 先摘掉它们，才不会被后面的第一人称判断误当成自述。
RECORD_POSSESSION = re.compile(
    r"(?:我的健康记录|我的记录|我的健康信息|我的健康数据|我的资料|我的信息|我的数据|"
    r"我的隐私|我之前的记录|我的病史记录|我的账号|我的账户|我保存的)"
)

# 第一人称：说明这段文字在讲用户自己。已在上一步摘掉他人与记录所有格。
PERSONAL = re.compile(r"(?:我|自己|本人|咱|俺)")

# 时间/频率：中文里大量自述不带主语（「最近总口渴」），靠时间词也能确认是在讲近况。
TEMPORAL = re.compile(
    r"(?:最近|近期|这几天|这两天|这周|这星期|这个月|这半年|这段时间|最近一段|"
    r"昨天|今天|前天|上周|上个月|去年|半年|几个月|一个多月|一个多星期|好几天|"
    r"多年|一直|总是|经常|时不时|偶尔|有时候|每天|长期|以前|向来|反复)"
)

# 自述行为动词：吃了/量了/停了药/去看了病这类，说明用户在做自己的健康管理。
SELF_CARE = re.compile(
    r"(?:吃了|喝着|喝了|停了|戒了|量了|测了|查了|看过|约了|开始吃|换成|加了药|减了药)"
)

BODY = re.compile(
    r"(?:脸上|面部|脸色|脸|眼睛|眼皮|耳朵|鼻子|嗓子|喉咙|咽喉|口腔|牙龈|牙齿|舌头|"
    r"头皮|头发|脖子|颈部|肩膀|后背|胸口|乳房|肚子|腹部|胃|肠|腰|屁股|膝盖|关节|"
    r"脚踝|脚|手指|手腕|胳膊|手臂|指甲|皮肤|肌肉|骨头|膀胱|尿道|肝|肾|肺|甲状腺|"
    r"淋巴|子宫|卵巢|痔疮|身体的|身体|体温)"
)

SENSATION = re.compile(
    r"(?:痛|疼|晕|恶心|想吐|呕吐|吐了|腹泻|拉肚子|便秘|大便|咳嗽|咳痰|干咳|咳|"
    r"发烧|发热|低烧|流鼻涕|鼻塞|打喷嚏|鼻痒|气喘|喘不上气|呼吸困难|憋气|胸闷|"
    r"心慌|心悸|心跳快|乏力|没力气|无力|疲惫|很累|容易累|犯困|嗜睡|失眠|睡不着|"
    r"睡眠不好|多梦|易醒|出汗|盗汗|怕冷|怕热|手脚冰凉|口渴|口干|嘴干|多饮|尿多|"
    r"尿频|尿急|尿痛|夜尿|食欲不振|没胃口|不想吃饭|吃得少|暴食|发痒|瘙痒|痒|"
    r"红肿|起疹|皮疹|红红|发红|起泡|脱皮|长痘|湿疹|荨麻疹|麻木|发麻|手抖|抽筋|"
    r"抽搐|浮肿|水肿|发炎|掉头发|脱发|视力模糊|看不清|耳鸣|变瘦|瘦了|长胖|胖了|"
    r"月经不调|痛经|绝经|怀孕|孕期|备孕|压力大|情绪|心情不好|烦躁|焦虑)"
)

MEDICATION = re.compile(
    r"(?:吃药|服药|用药|停药|漏服|加药|减药|剂量|抗生素|抗菌药|消炎药|止痛药|降压药|"
    r"降糖药|降脂药|胰岛素|激素|中药|西药|保健品|维生素|钙片|安眠药|抗过敏药|"
    r"过敏史|药物过敏|青霉素|头孢|阿司匹林|布洛芬|二甲双胍)"
)

ALLERGY_OR_LIFESTYLE = re.compile(
    r"(?:过敏|过敏体质|不能吃|吃了会|抽烟|吸烟|戒烟|香烟|烟龄|一包烟|几根烟|烟酒|"
    r"喝酒|饮酒|酗酒|一杯酒|酒精|熬夜|作息|饮食|吃素|外卖|咖啡|浓茶|运动|锻炼|"
    r"健身|跑步|久坐|减肥|节食|喝水)"
)

MEASUREMENT = re.compile(
    r"(?:血压|高压|低压|血糖|血脂|尿酸|心率|血氧|体重|身高|BMI|体检|化验|指标|度数|"
    r"mmHg|mmol|公斤|kg|厘米|cm|次/分)"
)

CARE_SEEKING = re.compile(
    r"(?:去医院|看病|看医生|就诊|就医|挂号|门诊|急诊|住院|出院|手术|开刀|复查|复诊|"
    r"抽血|拍片|核磁|B超|彩超|胃镜|肠镜|检查报告|化验单|诊断书)"
)

CONDITION = re.compile(
    r"(?:高血压|糖尿病|冠心病|心脏病|哮喘|慢阻肺|甲亢|甲减|胃炎|胃溃疡|鼻炎|咽炎|"
    r"颈椎病|腰椎间盘|关节炎|类风湿|痛风|结石|贫血|乙肝|丙肝|脂肪肝|癫痫|偏头痛|"
    r"中风|脑梗|心梗|肿瘤|癌症|肌瘤|囊肿|息肉|静脉曲张|前列腺|感冒|流感|中暑|"
    r"扭伤|拉伤|烫伤|烧伤|咬伤)"
)

HEALTH_PATTERNS = (
    BODY,
    SENSATION,
    MEDICATION,
    ALLERGY_OR_LIFESTYLE,
    MEASUREMENT,
    CARE_SEEKING,
    CONDITION,
)

# 短消息本身就是症状/用药/指标/就医陈述（「头晕」「拉肚子」「38度5」）时，不再要求主语或时间词。
# 只看身体部位（「身体健康很重要」）不算自述，避免把泛泛而谈当成用户事实送进抽取器。
BARE_SIGNAL_PATTERNS = (
    SENSATION,
    MEDICATION,
    MEASUREMENT,
    ALLERGY_OR_LIFESTYLE,
    CARE_SEEKING,
    CONDITION,
)
BARE_SELF_REPORT_MAX_CHARS = 12


def _decision(eligible: bool, reason: HealthEligibilityReason) -> HealthEligibilityDecision:
    return HealthEligibilityDecision(eligible=eligible, reason=reason)


def _matches(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def evaluate_health_extraction_eligibility(text: str) -> HealthEligibilityDecision:
    """Return whether one user message should be sent to the extractor.

    The decision is about framing only: the extractor still decides which facts (if any)
    are storable, and ``is_safe_fact`` filters inference, advice and identity data.
    """

    normalized = unicodedata.normalize("NFKC", text or "").strip()
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return _decision(False, "empty")
    if SOCIAL_ONLY.fullmatch(compact):
        return _decision(False, "social-only")

    residual = RECORD_POSSESSION.sub("", THIRD_PARTY.sub("", compact))
    personal = PERSONAL.search(residual) is not None
    health = _matches(HEALTH_PATTERNS, compact)
    personal_health = personal and health
    temporal = TEMPORAL.search(compact) is not None
    self_care = SELF_CARE.search(compact) is not None

    # 问“我已经存了什么”永远不是新的事实陈述，即使句中带第一人称与病名。
    if RECORD_QUERY.search(compact):
        return _decision(False, "record-query")

    if not personal_health:
        if IDENTITY_QUESTION.search(compact):
            return _decision(False, "identity-question")
        if PRODUCT_CAPABILITY.search(compact):
            return _decision(False, "product-capability")
        if OFF_TOPIC_REQUEST.search(compact):
            return _decision(False, "off-topic-request")

    if not health:
        return _decision(False, "no-health-content")
    if GENERAL_KNOWLEDGE.search(compact) and not personal:
        return _decision(False, "general-knowledge-question")
    if THIRD_PARTY.search(compact) and not personal:
        return _decision(False, "third-party")
    if personal or temporal or self_care:
        return _decision(True, "self-disclosure")
    if len(compact) <= BARE_SELF_REPORT_MAX_CHARS and _matches(BARE_SIGNAL_PATTERNS, compact):
        return _decision(True, "self-disclosure")
    return _decision(False, "no-personal-framing")
