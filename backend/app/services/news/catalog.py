"""候选来源登记册（代码内版本化）。

**登记 ≠ 启用**：这里只描述来源与实测事实，是否写入数据库并 `enabled=true` 由运维用前台
CLI 显式完成（`python -m app.news_cli --enable <id> --license-note "..."`），不落任何自启动。
"""

from dataclasses import dataclass

#: WHO 版权页（2026-10-04 实测 200）原文摘录。**仍需用户/法务确认**「科普门户」属于非商业用途，
#: 以及「新闻网页」是否都在该许可范围内——页面写的是「WHO 出版物」与「WHO materials」两处措辞。
_WHO_LICENSE_NOTE = (
    "WHO 版权页 https://www.who.int/about/policies/publishing/copyright 原文："
    "“Permission from WHO is not required for the use of WHO materials issued under the "
    "Creative Commons Attribution-NonCommercial-ShareAlike 3.0 IGO (CC BY-NC-SA 3.0 IGO) licence.”"
    "即非商业使用无需另行申请，但须署名、以相同方式共享、不得用于推广。"
    "本项目只存原题、来源、原文链接、发布时间与获取时间，不镜像正文、不转存其摘要字段。"
)


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
    license_note=_WHO_LICENSE_NOTE,
)

WHO_NEWS_RELEASES = SourceSpec(
    id="who_news_releases",
    name="WHO 新闻稿",
    organization="世界卫生组织（WHO）",
    homepage_url="https://www.who.int/news-room/news-releases",
    # 与暴发新闻同一套官方 OData 接口，只是栏目不同（2026-10-04 实测 HTTP 200 / JSON）。
    feed_url=(
        "https://www.who.int/api/news/newsitems"
        "?$top=20&$orderby=PublicationDateAndTime%20desc"
    ),
    fetch_mode="official_api",
    # 新闻稿覆盖公共卫生多个话题，暂归入「疾病」专区；这是本项目的取舍，不是来源自带的分类。
    category_scope=("disease",),
    license_note=_WHO_LICENSE_NOTE,
)

#: 已通过实测、可被 CLI 启用的来源。英文内容未做翻译，专区显示时按原题呈现。
CATALOG: dict[str, SourceSpec] = {
    WHO_DISEASE_OUTBREAK_NEWS.id: WHO_DISEASE_OUTBREAK_NEWS,
    WHO_NEWS_RELEASES.id: WHO_NEWS_RELEASES,
}

#: 已知但**不**可自动读取、仅记录障碍的来源（不加入 CATALOG，CLI 拒绝启用）。
#: 全部为 2026-10-04 实测：中文官方站点既没有机器可读订阅源，也没有可引用的再利用授权。
BLOCKED_SOURCES: dict[str, str] = {
    "nmpa_notices": (
        "国家药监局：首页实测 412（反爬拦截，此前记录的 robots 403 本轮复测为 404，"
        "即站点没有 robots.txt，但同样没有可用的订阅源或再利用授权）；需先取得许可与稳定入口。"
    ),
    "nhc_notices": (
        "国家卫健委：首页实测 412（反爬拦截），无 RSS/Atom 声明；需先取得许可与稳定入口。"
    ),
    "chinacdc_knowledge": (
        "中国疾控中心：首页 200、但健康主题路径 /jkzt/ 实测 404，且页面无 RSS/Atom 声明，"
        "只能靠人工或爬页面；需重新确认栏目地址与许可。"
    ),
    "sport_gov": (
        "国家体育总局：首页 200、无 RSS/Atom 声明、无再利用授权说明；只能爬页面，需先取得许可。"
    ),
    "cnsoc": (
        "中国营养学会：robots.txt 允许通用爬虫（`User-agent: *` 无 Disallow），但无 RSS/Atom 声明、"
        "无再利用授权说明；需先取得许可。"
    ),
}


def get_spec(source_id: str) -> SourceSpec | None:
    return CATALOG.get(source_id)