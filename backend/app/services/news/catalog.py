"""候选来源登记册（代码内版本化）。

**登记 ≠ 启用**：这里只描述来源与实测事实，是否写入数据库并 `enabled=true` 由运维用前台
CLI 显式完成（`python -m app.news_cli --enable <id> --license-note "..."`），不落任何自启动。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    id: str
    name: str
    organization: str
    homepage_url: str
    feed_url: str
    fetch_mode: str
    category_scope: tuple[str, ...]
    license_note: str


WHO_DISEASE_OUTBREAK_NEWS = SourceSpec(
    id="who_disease_outbreak_news",
    name="WHO 疾病暴发新闻",
    organization="世界卫生组织（WHO）",
    homepage_url="https://www.who.int/emergencies/disease-outbreak-news",
    # 官方 Sitefinity OData 接口；2026-10-04 实测 HTTP 200 / application/json，$top 分页可用。
    feed_url=(
        "https://www.who.int/api/news/diseaseoutbreaknews"
        "?$top=20&$orderby=PublicationDateAndTime%20desc"
    ),
    fetch_mode="official_api",
    category_scope=("disease",),
    license_note=(
        "技术可读性已实测（HTTP 200，application/json，条目 URL 形如 "
        "https://www.who.int/emergencies/disease-outbreak-news/item/<DonId>）；"
        "**再利用许可未核验**：WHO 网站条款与内容署名/非商业要求"
        "需用户或法务确认后才可正式启用以外的用途。"
        "本项目只存原题、来源、原文链接、发布时间与获取时间，不镜像正文、不转存其摘要字段。"
    ),
)

#: 已通过实测、可被 CLI 启用的来源。英文内容未做翻译，专区显示时按原题呈现。
CATALOG: dict[str, SourceSpec] = {
    WHO_DISEASE_OUTBREAK_NEWS.id: WHO_DISEASE_OUTBREAK_NEWS,
}

#: 已知但**不**可自动读取、仅记录障碍的来源（不加入 CATALOG，CLI 拒绝启用）。
BLOCKED_SOURCES: dict[str, str] = {
    "nmpa_notices": (
        "国家药监局：robots.txt 返回 403，栏目页虽可读（200）但站点明确不希望被自动访问；"
        "需先取得许可。2026-10-04 实测。"
    ),
    "chinacdc_knowledge": (
        "中国疾控中心：robots.txt 404，曾探测的健康主题路径 /jkzt/ 现为 404；"
        "需重新确认栏目地址与许可。2026-10-04 实测。"
    ),
}


def get_spec(source_id: str) -> SourceSpec | None:
    return CATALOG.get(source_id)