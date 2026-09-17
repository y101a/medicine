from __future__ import annotations

from xml.etree import ElementTree

import httpx

from app.ai.mcp.models import PubMedArticle, PubMedSearchResult
from app.ai.mcp.validation import validate_limit, validate_topic

PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_QUERIES = {
    "甲状腺结节": "thyroid nodule",
    "甲状腺功能亢进": "hyperthyroidism",
    "甲状腺功能减退": "hypothyroidism",
    "甲状腺疾病": "thyroid diseases",
    "鼻窦炎": "sinusitis",
    "鼻炎": "rhinitis",
    "胃食管反流": "gastroesophageal reflux disease",
    "胃炎": "gastritis",
    "胃溃疡": "stomach ulcer",
    "胆囊炎": "cholecystitis",
    "胆结石": "cholelithiasis",
    "脂肪肝": "nonalcoholic fatty liver disease",
    "肾结石": "kidney stones",
    "尿路感染": "urinary tract infection",
    "高血压": "hypertension",
    "糖尿病": "diabetes mellitus",
    "低血糖": "hypoglycemia",
    "高血脂": "hyperlipidemia",
    "冠心病": "coronary artery disease",
    "脑卒中": "stroke",
    "哮喘": "asthma",
    "肺炎": "pneumonia",
    "支气管炎": "bronchitis",
    "流感": "influenza",
    "普通感冒": "common cold",
    "新冠": "COVID-19",
    "带状疱疹": "herpes zoster",
    "荨麻疹": "urticaria",
    "湿疹": "eczema",
    "贫血": "anemia",
    "痛风": "gout",
    "类风湿关节炎": "rheumatoid arthritis",
    "骨质疏松": "osteoporosis",
    "偏头痛": "migraine",
    "颈椎病": "cervical spondylosis",
    "痔疮": "hemorrhoids",
    "狂犬病": "rabies",
    "乙肝": "hepatitis B",
    "幽门螺杆菌": "Helicobacter pylori",
    "抑郁症": "depressive disorder",
    "焦虑症": "anxiety disorders",
}


class ExternalToolError(RuntimeError):
    """Provider failure with a stable, non-sensitive message."""


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return value or None


def _parse_articles(xml_text: str) -> list[PubMedArticle]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise ExternalToolError("PUBMED_RESPONSE_INVALID") from exc

    articles: list[PubMedArticle] = []
    for item in root.findall(".//PubmedArticle"):
        citation = item.find("MedlineCitation")
        article = citation.find("Article") if citation is not None else None
        pmid = _text(citation.find("PMID")) if citation is not None else None
        title = _text(article.find("ArticleTitle")) if article is not None else None
        if not pmid or not title:
            continue
        abstract_parts: list[str] = []
        if article is not None:
            for part in article.findall("Abstract/AbstractText"):
                value = _text(part)
                if value:
                    label = part.attrib.get("Label")
                    abstract_parts.append(f"{label}: {value}" if label else value)
        journal = _text(article.find("Journal/Title")) if article is not None else None
        published = None
        if article is not None:
            pub_date = article.find("Journal/JournalIssue/PubDate")
            if pub_date is not None:
                published = _text(pub_date.find("Year")) or _text(pub_date.find("MedlineDate"))
        doi = None
        for article_id in item.findall("PubmedData/ArticleIdList/ArticleId"):
            if article_id.attrib.get("IdType") == "doi":
                doi = _text(article_id)
                break
        articles.append(
            PubMedArticle(
                pmid=pmid,
                title=title,
                abstract="\n".join(abstract_parts) or None,
                journal=journal,
                published=published,
                doi=doi,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            )
        )
    return articles


async def search_pubmed(
    topic: str,
    *,
    max_results: int = 5,
    api_key: str | None = None,
    tool_name: str = "medical_assistant",
    email: str | None = None,
    timeout_seconds: float = 10,
    client: httpx.AsyncClient | None = None,
) -> PubMedSearchResult:
    canonical_topic = validate_topic(topic)
    limit = validate_limit(max_results)
    query = PUBMED_QUERIES[canonical_topic]
    common_params = {"tool": tool_name}
    if email:
        common_params["email"] = email
    if api_key:
        common_params["api_key"] = api_key

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 4))
    )
    try:
        search_response = await active_client.get(
            f"{PUBMED_BASE_URL}/esearch.fcgi",
            params={
                **common_params,
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": limit,
                "sort": "pub date",
            },
        )
        search_response.raise_for_status()
        payload = search_response.json()
        identifiers = payload.get("esearchresult", {}).get("idlist", [])
        valid_identifiers = isinstance(identifiers, list) and all(
            str(value).isdigit() for value in identifiers
        )
        if not valid_identifiers:
            raise ExternalToolError("PUBMED_RESPONSE_INVALID")
        if not identifiers:
            return PubMedSearchResult(topic=canonical_topic, query=query, count=0, articles=[])

        fetch_response = await active_client.get(
            f"{PUBMED_BASE_URL}/efetch.fcgi",
            params={
                **common_params,
                "db": "pubmed",
                "id": ",".join(str(value) for value in identifiers),
                "retmode": "xml",
            },
        )
        fetch_response.raise_for_status()
        articles = _parse_articles(fetch_response.text)[:limit]
        return PubMedSearchResult(
            topic=canonical_topic,
            query=query,
            count=len(articles),
            articles=articles,
        )
    except ExternalToolError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ExternalToolError("PUBMED_REQUEST_FAILED") from exc
    finally:
        if owns_client:
            await active_client.aclose()
