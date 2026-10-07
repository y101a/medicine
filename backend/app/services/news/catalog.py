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
    # 综合新闻稿仅保留标题明确涉及疾病/传染病防控的条目，其余不入疾病专区。
    category_scope=("disease",),
    license_note=_WHO_LICENSE_NOTE,
)

WHO_ZH_NEWS = SourceSpec(
    id="who_zh_news",
    name="世卫组织中文新闻",
    organization="世界卫生组织（WHO）",
    homepage_url="https://www.who.int/zh/news-room",
    feed_url="https://www.who.int/zh/news-room",
    fetch_mode="approved_page",
    category_scope=("disease",),
    license_note=(
        _WHO_LICENSE_NOTE + "中文新闻列表 2026-10-06 用项目受控抓取器实测 200；"
        "仅保存同域中文原题、日期和原文链接，按疾病词筛选，不复制正文或摘要。"
    ),
)

BEIJING_WJW_HEALTH = SourceSpec(
    id="beijing_wjw_health",
    name="北京市卫生健康委员会",
    organization="北京市卫生健康委员会",
    homepage_url="https://wjw.beijing.gov.cn/xwzx_20031/xwfb/",
    feed_url="https://wjw.beijing.gov.cn/xwzx_20031/xwfb/",
    fetch_mode="approved_page",
    category_scope=("wellness", "disease", "medication"),
    license_note=(
        "北京市卫健委《法律声明》 https://wjw.beijing.gov.cn/sy_20013/202004/"
        "t20200401_1781806.html：本站自有内容如需使用或转载需注明转载来源。"
        "仅保存本站刊载的中文原题、列表日期和原文链接，不复制正文/摘要/图片；"
        "列表未标注稿件原始作者，展示来源名只表示刊载网站。"
        "2026-10-06 项目 httpx 经定向直连可读，其他来源保持原代理行为。"
    ),
)

ECDC_NEWS = SourceSpec(
    id="ecdc_news",
    name="ECDC 新闻与公告",
    organization="欧洲疾病预防控制中心（ECDC）",
    homepage_url="https://www.ecdc.europa.eu/en/news-events",
    # ECDC 官方 RSS 列表指向该地址；2026-10-05 本机实测 200/application/rss+xml。
    feed_url="https://www.ecdc.europa.eu/en/taxonomy/term/1307/feed",
    fetch_mode="rss",
    category_scope=("disease",),
    license_note=(
        "ECDC 官网新闻 RSS，2026-10-05 实测可读；版权页说明其自有网页内容默认 "
        "CC BY 4.0，需署名、链接许可并标明改动；第三方材料不在许可内。"
        "本项仅为待启用候选，门户完成许可归属和翻译标注展示前不得启用。"
    ),
)

NMPAIC_NEWS = SourceSpec(
    id="nmpaic_news",
    name="国家药监局信息中心要闻",
    organization="国家药品监督管理局信息中心",
    homepage_url="https://www.nmpaic.org.cn/yjzxyw/",
    feed_url="https://www.nmpaic.org.cn/yjzxyw/",
    fetch_mode="html_list",
    category_scope=("medication",),
    license_note=(
        "2026-10-05 栏目静态 HTML 可读；仅收标题、原文链接和列表日期，"
        "不复制正文、图片或摘要。启用前需人工核对具体条目的原始发布者、"
        "网站使用条件与门户来源标注；转载稿不得误标为该中心原创。"
    ),
)

CHINANUTRI_EDUCATION = SourceSpec(
    id="chinanutri_health_education",
    name="中国疾控中心营养与健康所科普",
    organization="中国疾病预防控制中心营养与健康所",
    homepage_url="https://www.chinanutri.cn/yyjkzxpt/yyjkkpzx/hdjl/",
    feed_url="https://www.chinanutri.cn/yyjkzxpt/yyjkkpzx/hdjl/",
    fetch_mode="html_list",
    category_scope=("wellness", "fitness"),
    license_note=(
        "2026-10-05 栏目静态 HTML 可读，含中文标题、同域文章链接与日期；"
        "仅拟保存这些元数据，不复制正文或图片。网站页脚声明版权所有，"
        "公开使用条件及转载稿归属仍待核对，故暂不允许启用。"
    ),
)

ODPHP_FITNESS = SourceSpec(
    id="odphp_physical_activity",
    name="ODPHP 身体活动资讯",
    organization="美国卫生与公众服务部疾病预防与健康促进办公室（ODPHP）",
    homepage_url="https://odphp.health.gov/news/tag/physical-activity?page=0",
    feed_url="https://odphp.health.gov/news/tag/physical-activity?page=0",
    fetch_mode="approved_page",
    category_scope=("fitness",),
    license_note=(
        "ODPHP https://odphp.health.gov/copyright-policy 说明本站文字属于公共领域，"
        "使用须注明 ODPHP 并链接本站；仅取专题列表标题、日期和原文链接，"
        "不复制图片/摘要/正文，不暗示机构背书。2026-10-05 httpx 200；robots.txt 未限制 /news/。"
    ),
)

ODPHP_NUTRITION = SourceSpec(
    id="odphp_food_nutrition",
    name="ODPHP 营养与健康饮食资讯",
    organization="美国卫生与公众服务部疾病预防与健康促进办公室（ODPHP）",
    homepage_url="https://odphp.health.gov/news/tag/food-and-nutrition?page=0",
    feed_url="https://odphp.health.gov/news/tag/food-and-nutrition?page=0",
    fetch_mode="approved_page",
    category_scope=("wellness",),
    license_note=(
        "ODPHP https://odphp.health.gov/copyright-policy 说明本站文字属于公共领域，"
        "使用须注明 ODPHP 并链接本站；仅取专题列表标题、日期和原文链接，"
        "不复制图片/摘要/正文，不暗示机构背书。2026-10-05 httpx 200；robots.txt 未限制 /news/。"
    ),
)

FDA_DRUG_UPDATES = SourceSpec(
    id="fda_drug_updates",
    name="FDA 药物审批与安全资讯",
    organization="美国食品药品监督管理局（FDA）",
    homepage_url="https://www.fda.gov/drugs/news-events-human-drugs/whats-new-related-drugs",
    # 官网“RSS Feed for This Page”的真实链接；先前猜测的小写 /drugs/rss.xml 是 404。
    feed_url="https://www.fda.gov/AboutFDA/ContactFDA/StayInformed/RSSFeeds/Drugs/rss.xml",
    fetch_mode="rss",
    category_scope=("medication",),
    license_note=(
        "FDA https://www.fda.gov/about-fda/about-website/website-policies 说明本站自有文字"
        "默认公共领域并允许链接，建议链接原文；只取原题、日期、同域 HTTPS 原文链接，"
        "过滤行政/技术动态及第三方内容。2026-10-05 官网 RSS 链接经重定向后 httpx 200。"
    ),
)

#: 已通过实测、可被 CLI 启用的来源。英文内容未做翻译，专区显示时按原题呈现。
CATALOG: dict[str, SourceSpec] = {
    WHO_DISEASE_OUTBREAK_NEWS.id: WHO_DISEASE_OUTBREAK_NEWS,
    WHO_NEWS_RELEASES.id: WHO_NEWS_RELEASES,
    WHO_ZH_NEWS.id: WHO_ZH_NEWS,
    BEIJING_WJW_HEALTH.id: BEIJING_WJW_HEALTH,
    ODPHP_FITNESS.id: ODPHP_FITNESS,
    ODPHP_NUTRITION.id: ODPHP_NUTRITION,
    FDA_DRUG_UPDATES.id: FDA_DRUG_UPDATES,
}

# 技术可读但展示许可条件尚未接线；不放入 CATALOG，CLI 因而无法启用。
PENDING_SOURCES: dict[str, SourceSpec] = {
    ECDC_NEWS.id: ECDC_NEWS,
    NMPAIC_NEWS.id: NMPAIC_NEWS,
    CHINANUTRI_EDUCATION.id: CHINANUTRI_EDUCATION,
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
