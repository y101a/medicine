# 新闻中文化与来源扩展：2026-10-05 核验记录

状态：部分实现，**未启用新来源、未调用付费翻译**。项目已有 WHO 两个英文新闻源；本轮只核验候选并增加可追溯译题的数据/API 字段，不能宣称页面已中文化。

专区相关性：`who_news_releases` 是综合新闻稿，不能整源归为疾病。适配器现在仅保留原标题明确命中疾病、传染病或免疫接种术语的条目；行政任命等综合动态不再入库。该保守标题筛选可能漏掉相关但标题不含术语的稿件，不是医学审核。已经入库的不相关旧条目仍按原展示有效期自然过期，本次不直接删除用户数据或新闻快照。

## 来源核验

| 候选 | 官方入口与本机只读实测 | 处理 |
| --- | --- | --- |
| ECDC 新闻/公告 | [官方 RSS 列表](https://www.ecdc.europa.eu/en/rss-feeds) 链接到 `https://www.ecdc.europa.eu/en/taxonomy/term/1307/feed`；2026-10-05 本机 GET 为 200、`application/rss+xml`，条目含原题、HTTPS 原文 URL、发布时间 | 已增加 `ecdc_news` 待启用候选和离线适配测试；**未加入可启用目录**，先补门户 ECDC 署名、[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 许可链接与译题改动标记，并排除第三方版权条目。许可依据：[ECDC 知识产权声明](https://www.ecdc.europa.eu/en/ecdc-intellectual-property-notices)。 |
| FDA 官网 RSS | [官方 RSS 列表](https://www.fda.gov/about-fda/contact-fda/subscribe-podcasts-and-news-feeds)列消费者健康、MedWatch、药品更新等；但本机直取其页面指向的 `consumers/rss.xml`、`medwatch/rss.xml`、`drugs/rss.xml`、`fda-outbreaks/rss.xml` 均为 404 | 不接入死链接。其[网站政策](https://www.fda.gov/about-fda/about-website/website-policies)允许多数站内自有文字再利用，但需要先找到稳定机器可读入口。 |
| NIH 新闻 RSS | [NIH 新闻页](https://www.nih.gov/news-events/news-releases)列 `feed.xml`；本机请求返回 403 | 不绕过拦截，不接入。 |
| CDC 旅行通告 RSS | [CDC 官方 RSS 页面](https://wwwnc.cdc.gov/travel/page/rss)列 `notices.xml`；本机请求虽然 200，但返回 `text/html`，不是 RSS | 不把 HTML 误当 feed。 |
| MedlinePlus RSS | [官方 RSS 页面](https://medlineplus.gov/rss.html)存在，但[官方使用条款](https://medlineplus.gov/about/using/usingcontent/)明确称 RSS 仅供个人使用，不允许在网站/信息服务中使用 | 明确排除。 |
| 国家药监局信息中心·要闻 | `https://www.nmpaic.org.cn/yjzxyw/` 2026-10-05 本机 GET 200，静态 HTML 含同域文章路径、中文原题和列表日期；实页只读解析 15 条 | `nmpaic_news` 已登记为待启用候选，增加专用 HTML 列表适配器；仅抽取元数据。启用前核对站点使用条件、转载稿原始发布者和门户标注，当前不自动采集入库。 |
| 中国疾控中心·健康提示及营养 | 栏目网页可见；[版权与免责声明](https://www.chinacdc.cn/mzsm/)对转载、链接及复制发表有具体要求 | 暂不自动聚合，先取得授权或明确适用方式。 |
| 健康报网 | [网站声明](https://www.jkb.com.cn/jkbactivists/2024/0125/492985.html)限制未经书面授权转载、链接 | 明确排除，除非取得书面授权。 |
| 国家体育总局·健身指导 | [信息转发说明](https://www.sport.gov.cn/n323/n10459/c24206655/content.html)要求标明原公开主体与出处；本机 HTTPS 请求遇 `UNEXPECTED_EOF_WHILE_READING`，无法用项目 HTTP 客户端读取 | 保留候选，不绕过连接失败；待可读时还要识别转载稿的原始来源。 |
| 北京、江苏卫健委及国家卫健委 | 栏目存在，但本机官方站点出现 TLS 连接失败或此前 412，且未找到可稳定读取的机器订阅入口 | 暂不启用；不绕过拦截。 |
| 国家药监局药审中心 | 首页可读，主要是专业审评通知；尚未核对具体栏目使用条件与适合普通用户的条目范围 | 暂不启用。 |
| 福建省卫健委 RSS 订阅 | [官方说明页](https://wjw.fujian.gov.cn/bzzx/rssdy/) 明确提供「卫生要闻、八闽动态、公示公告」RSS，且说明可用 RSS 阅读器订阅；但本机 2026-10-05 HTTPS GET 返回 unexpected EOF，未取得并实测确切 feed URL/条目字段 | 暂不登记为可启用来源；先解决正常连接并验证 RSS 地址、原文 URL、日期和使用条件。该栏目以政务工作动态为主，也不能直接当作养生/健身新闻。 |
| 国家药监局 UDI 订阅 | [官方订阅说明](https://udi.nmpa.gov.cn/showRssDescription.html) 给出 `https://udi.nmpa.gov.cn/rss/download.html?files=daily` 等地址；内容是医疗器械唯一标识数据库下载发布文件，不是面向公众的药物新闻 | 不接入新闻门户，不能为了填满“药物”专区而误分类。 |
| 中国疾控中心营养与健康所·营养健康科普 | [官方栏目](https://www.chinanutri.cn/yyjkzxpt/yyjkkpzx/hdjl/) 的静态 HTML 有中文原题、日期与同域文章链接；2026-10-05 `Invoke-WebRequest` 为 200，但项目 `httpx` 直取返回 445/空体。网站页脚标“版权所有”，使用条件仍待核对。 | 已实现仅提取列表元数据的离线适配器和养生/健身标题分类测试，登记为 `PENDING_SOURCES`；**不加入可启用目录**、不绕过 445。该栏目更新并非每天，不能以“每日刷新”承诺每日有新文章。 |
| ODPHP 身体活动 | [官方身体活动专题](https://odphp.health.gov/news/tag/physical-activity?page=0)；2026-10-05 项目 `httpx` 和受控抓取器均为 200、HTML 有同域标题/日期/原文链接；`robots.txt` 未限制 `/news/`。[版权政策](https://odphp.health.gov/copyright-policy)说明文字属公共领域，须署名并链接来源。 | `odphp_physical_activity` 已在开发库启用并首次试抓，仅保留标题明显涉及健身/活动的条目，不存摘要/图片/正文；原题为英文。 |
| ODPHP 食品与营养 | [官方食品与营养专题](https://odphp.health.gov/news/tag/food-and-nutrition?page=0)；2026-10-05 项目 `httpx` 为 200，许可同上；本次首屏可解析 2 条相关标题，但日期均在 2025 年，**近期供给不足**。 | 新增 `odphp_food_nutrition` 可启用候选及专用解析器；不承诺当前养生专区有近期新闻，需继续扩源。尚未在数据库启用，原题为英文。 |
| FDA 药物 RSS | [FDA 药物更新页](https://www.fda.gov/drugs/news-events-human-drugs/whats-new-related-drugs) 的“RSS Feed for This Page”实际指向大小写路径 `/AboutFDA/ContactFDA/StayInformed/RSSFeeds/Drugs/rss.xml`；2026-10-05 项目受控抓取器跟随重定向后取得 RSS 200。官方[网站政策](https://www.fda.gov/about-fda/about-website/website-policies)允许链接 FDA 自有内容。 | `fda_drug_updates` 已在开发库启用并首次试抓；过滤行政/技术条目及外站链接，HTTP 原文地址升为 FDA 同域 HTTPS，仅取药物审批/安全标题、日期和链接。原题为英文。 |

以上是技术可达性与公开政策核验，**不是逐条医学审核，也不是最终法律意见**。来源扩展不能为填满四分区而放宽准入。

2026-10-06 首次试抓（北京时间凌晨，系统更新日记为 2026-10-05）：用户同意后仅在本机开发库启用 `odphp_physical_activity` 与 `fda_drug_updates`。前者抓取/新增 3 条，均为 2026 年 4–7 月旧稿；后者抓取/新增 1 条，发表于 2026-10-02。两来源最近错误均为 `None`，分类展示期计数分别为健身 3、药物 1。`odphp_food_nutrition` 继续未启用，养生 0。已入库条目未逐条医学审核，仍须显示原来源、发布日期及未审核状态；每日检查不保证每日有新稿。

## 中文来源优先（2026-10-06）

- [北京市卫健委新闻发布](https://wjw.beijing.gov.cn/xwzx_20031/xwfb/)：DSH 已提供 5 条最小 HTML 夹具（根目录 `NEWS_SOURCE_CANDIDATES.md` §11.4）。依据[官方法律声明](https://wjw.beijing.gov.cn/sy_20013/202004/t20200401_1781806.html)，仅保存本站刊载的中文原题、列表显示日期和同域链接，不复制摘要、正文、图片；来源名表示刊载网站，不推定其为稿件原始作者。经用户 2026-10-06 明确许可，仅本来源在受控抓取器中设置 `trust_env=False` 直连；其他来源仍遵从 Windows 系统代理。原有逐跳公开 HTTPS/SSRF 校验保持，直连时跨域重定向拒绝。真实列表请求 200、25660 B，专用适配器按标题相关性筛出 13 条（养生 7、疾病 6、药物 0），未见行政活动标题。**开发库已启用并首次抓取：run=344，`succeeded`，抓取/新增 13、拒收 0、最近错误 `None`。**中文原题存 `title`，`title_zh`/`title_zh_source` 保持空，不冒充译题。该栏目更新并非每日有新稿，列表现有条目最晚为 2026-09-25。

- [WHO 中文媒体中心](https://www.who.int/zh/news-room)：项目受控抓取器返回 `text/html`、87010 字节；专用适配器仅从列表卡片提取中文原题、发布日期和 WHO 同域 `/zh/news/item/` 链接，按标题中的疾病关键词保守归入疾病区。`who_zh_news` 已在开发库启用，首次抓取 2、入库 2、拒收 0，均发表于 2026-09-25。来源许可按现有 WHO 条件处理，不复制摘要、正文或图片。
- [中国疾控中心食物营养栏目](https://www.chinacdc.cn/jkkp/yyjk/swyy/)：项目抓取器返回 `text/html`、29610 字节，存在中文标题和日期。但其[版权与免责声明](https://www.chinacdc.cn/mzsm/202410/t20241028_302192.html)对转载、链接及来源署名有额外条件；不把“技术可读”当作可直接启用，先由运营/法务确认标题加链接的展示方式。未接入目录，未入库。
- [国家卫健委健康科普辟谣平台](https://www.nhc.gov.cn/kppypt/index.shtml)：当前环境项目受控抓取器报 `FETCH_FAILED`，不绕过限制。已在 `COORDINATION.md` §6 请求 DSH 从其环境核验可达性和使用条件。
- **当前效果边界**：养生已有 7 条北京中文稿；疾病新增 6 条北京中文稿，加上原有 WHO 中文稿 2 条，但默认按发布时间倒序，较新的英文 WHO 稿仍可能排在前面。健身、药物尚无已启用的中文来源。不能据此宣称新闻页已整体中文化；继续优先补合法、可稳定读取的中文专区来源，英文保持补充。

## 中文标题实现边界

- `news_items.title` 始终保留原题；新增可空 `title_zh` 和 `title_zh_source=machine|manual`，API 返回 `titleZh` / `titleZhSource`。翻译不改原题、原文链接、发布时间或去重指纹。
- 后续前端应在有 `titleZh` 时显示中文译题、英文原题和「机器翻译·未经医学审核」/「人工核对译题」标记；无译题时继续显示英文原题，不用空字符串冒充中文。
- 用户已明确选择**暂不启用付费翻译**。本轮不调用 Qwen 或其他付费服务；可由运营人员在人工核对后用前台 CLI `python -m app.news_cli --set-title-zh <ITEM_UUID> --zh-title "中文译题"` 录入，服务端校验长度、汉字与 HTML，保存为 `titleZhSource=manual`，原题不变。要做到每日新标题自动中文化，需要以后另行批准翻译服务或本地模型及其资源成本；当前不虚称自动完成。
- 新迁移 `20261005_0030` 已于 2026-10-05 在本机开发库应用；本文件新增的国内候选来源均未启用，不代表新闻门户已有中文资讯。

## 给前端的现行接口边界

- 新增的三个来源沿用现有 `GET /api/v1/news` 契约：`sourceStatuses[].categories` 分别是 `fitness`、`wellness`、`medication`，条目字段和分页字段均不变。只有运营人员通过 CLI 明确启用并刷新后，页面才可能出现条目。
- 原题仍是英文；用户此前拒绝付费自动翻译，后端不会为这些来源自动生成 `titleZh`。前端须如实显示英文原题和原文链接，不能把来源名或机器加工结果冒充中文译题。
- 专题页/订阅源不是每日都有新稿，`nextRefreshAt` 代表下次检查时间，不代表届时必有新条目。小贴士仍为空，不从新闻自动改写。
