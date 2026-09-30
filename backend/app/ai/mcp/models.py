from pydantic import BaseModel, Field


class PubMedArticle(BaseModel):
    pmid: str
    title: str
    abstract: str | None = None
    journal: str | None = None
    published: str | None = None
    doi: str | None = None
    url: str


class PubMedSearchResult(BaseModel):
    topic: str
    query: str
    count: int
    articles: list[PubMedArticle]
    notice: str = "PubMed 文献仅供资料检索，不替代医学审核、诊断或治疗建议。"


class AmapPoi(BaseModel):
    poi_id: str | None = None
    name: str
    address: str | None = None
    telephone: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    navigation_url: str | None = None


class AmapPoiResult(BaseModel):
    city: str
    department: str
    count: int
    pois: list[AmapPoi]
    notice: str = Field(default="结果来自公开 POI，可能过期；就诊前请向机构核实科室、时间和资质。")


class HospitalRoute(BaseModel):
    poi_id: str | None = None
    name: str
    address: str | None = None
    telephone: str | None = None
    district: str | None = None
    straight_distance_meters: int | None = None
    route_distance_meters: int | None = None
    route_duration_seconds: int | None = None
    route_mode: str
    navigation_url: str


class NearbyHospitalResult(BaseModel):
    route_mode: str
    count: int
    hospitals: list[HospitalRoute]
    notice: str = Field(
        default=(
            "按高德预计路线时间排序，仅供就医查找参考；最近不等于最适合。危急情况请立即拨打 120。"
        )
    )
