import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.rag.web_search import safe_search_topic

RetrievalGateReason = Literal["medical_content", "non_medical_content"]


@dataclass(frozen=True, slots=True)
class RetrievalGateDecision:
    should_retrieve: bool
    reason: RetrievalGateReason


EXACT_SOCIAL_CHAT = re.compile(
    r"^(?:你好|您好|嗨|hi|hello|早上好|上午好|下午好|晚上好|谢谢|感谢|再见|拜拜)"
    r"(?:呀|啊|哦|哈|！|!|。|\s)*$",
    re.IGNORECASE,
)
NON_MEDICAL_INTENT = re.compile(
    r"(?:你是谁|什么模型|哪个模型|介绍一下你自己|你会什么|讲个笑话|写代码|写文章|"
    r"翻译|今天天气|怎么登录|怎么注册|如何使用(?:这个)?系统|切换模型|上传头像|修改头像)"
)
SYMPTOM_OR_CONDITION = re.compile(
    r"(?:头痛|头疼|胸痛|胸闷|腹痛|肚子痛|胃痛|腰痛|关节痛|牙痛|咽痛|疼痛|"
    r"发热|发烧|低烧|咳嗽|咳痰|流鼻涕|鼻塞|气喘|呼吸困难|心慌|心悸|头晕|眩晕|"
    r"恶心|呕吐|腹泻|便秘|出血|红肿|水肿|皮疹|瘙痒|麻木|无力|乏力|抽搐|昏迷|"
    r"失眠|睡不着|焦虑|抑郁|自伤|过敏|感染|咬伤|烫伤|烧伤|血压|血糖|心率|"
    r"血脂|体温|月经|怀孕|孕期|产后|减肥|体重异常|食欲不振|身体不舒服|"
    r"胃不舒服|总是很累|血尿|尿频|尿急|尿痛|风团)"
)
MEDICAL_ENTITY = re.compile(
    r"(?:感冒|流感|肺炎|高血压|糖尿病|冠心病|脑卒中|中风|哮喘|癫痫|肿瘤|癌症|"
    r"狂犬病|传染病|抗生素|抗菌药|处方药|药物|用药|服药|疫苗|手术|治疗|康复|"
    r"检查报告|化验结果|体检|指标异常|挂什么科|挂哪个科|就医|急诊|看医生|"
    r"疾病|症状|病因|副作用|禁忌|诊断|预防|急救|心肺复苏|健康问题|医学术语|"
    r"营养|饮食健康|湿疹|荨麻疹)"
)
DISEASE_SUFFIX = re.compile(
    r"(?:(?:什么是|得了|患有|确诊(?:为)?|怀疑(?:是)?|了解|关于)\s*"
    r"[\u4e00-\u9fff]{1,10}(?:病|炎|癌|症|综合征)|"
    r"[\u4e00-\u9fff]{1,10}(?:病|炎|癌|症|综合征)"
    r"(?:怎么办|怎么治|严重吗|会好吗|传染吗|吃什么药))"
)


def evaluate_retrieval_gate(text: str) -> RetrievalGateDecision:
    normalized = unicodedata.normalize("NFKC", text).strip().lower()
    if EXACT_SOCIAL_CHAT.fullmatch(normalized):
        return RetrievalGateDecision(False, "non_medical_content")

    has_medical_signal = bool(
        safe_search_topic(normalized)
        or SYMPTOM_OR_CONDITION.search(normalized)
        or MEDICAL_ENTITY.search(normalized)
        or DISEASE_SUFFIX.search(normalized)
    )
    if NON_MEDICAL_INTENT.search(normalized) and not has_medical_signal:
        return RetrievalGateDecision(False, "non_medical_content")
    if has_medical_signal:
        return RetrievalGateDecision(True, "medical_content")
    return RetrievalGateDecision(False, "non_medical_content")
