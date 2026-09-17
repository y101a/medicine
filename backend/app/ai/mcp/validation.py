import re
import unicodedata

from app.rag.web_search import TOPICS

DEPARTMENTS = (
    "全科",
    "急诊科",
    "内科",
    "外科",
    "儿科",
    "妇科",
    "产科",
    "眼科",
    "耳鼻喉科",
    "口腔科",
    "皮肤科",
    "精神科",
    "心理科",
    "神经内科",
    "心内科",
    "呼吸科",
    "消化科",
    "内分泌科",
    "肾内科",
    "泌尿外科",
    "骨科",
    "风湿免疫科",
    "感染科",
    "肿瘤科",
    "康复科",
)
CITY_PATTERN = re.compile(r"(?:\d{6}|[\u4e00-\u9fff]{2,12})\Z")


class ToolInputError(ValueError):
    """Safe validation error whose message contains no submitted raw text."""


def validate_topic(topic: str) -> str:
    normalized = unicodedata.normalize("NFKC", topic).strip()
    if normalized not in TOPICS:
        raise ToolInputError("仅支持系统固定白名单中的通用病名，不得提交患者原文")
    return normalized


def validate_city(city: str) -> str:
    normalized = unicodedata.normalize("NFKC", city).strip()
    if not CITY_PATTERN.fullmatch(normalized):
        raise ToolInputError("城市须为 2-12 个中文字符或 6 位行政区编码，不得提交详细地址")
    return normalized


def validate_department(department: str) -> str:
    normalized = unicodedata.normalize("NFKC", department).strip()
    if normalized not in DEPARTMENTS:
        raise ToolInputError("科室不在系统允许的通用科室白名单中")
    return normalized


def validate_limit(limit: int) -> int:
    if limit < 1 or limit > 10:
        raise ToolInputError("返回数量必须为 1-10")
    return limit


def validate_coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    if not 3 <= latitude <= 54 or not 73 <= longitude <= 136:
        raise ToolInputError("当前位置须位于中国大陆常用经纬度范围内")
    return round(latitude, 6), round(longitude, 6)


def validate_route_mode(mode: str) -> str:
    if mode not in {"driving", "walking"}:
        raise ToolInputError("路线方式仅支持 driving 或 walking")
    return mode
