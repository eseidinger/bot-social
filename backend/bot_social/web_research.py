"""Bounded retrieval of public text pages for verifiable research passages."""

import http.client
import ipaddress
import os
import re
import socket
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
MAX_PROMPT_CHARS = 16_000
TIMEOUT_SECONDS = 10
HOST_PATTERN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
PUBMED_HOST = "pubmed.ncbi.nlm.nih.gov"
PUBMED_API_HOST = "eutils.ncbi.nlm.nih.gov"
PUBMED_ARTICLE_PATH = re.compile(r"/([1-9]\d{0,9})/?\Z")


class ResearchFetchError(ValueError):
    """A page could not be safely used as research material."""


def configured_research_hosts() -> tuple[str, ...] | None:
    raw = os.getenv("BOT_SOCIAL_RESEARCH_HOSTS")
    if raw is None:
        return None
    hosts = tuple(part.strip().lower() for part in raw.split(","))
    if not hosts or len(hosts) > 20 or any(not HOST_PATTERN.fullmatch(host) for host in hosts):
        raise ValueError("BOT_SOCIAL_RESEARCH_HOSTS must contain 1-20 DNS hostnames")
    if len(set(hosts)) != len(hosts):
        raise ValueError("BOT_SOCIAL_RESEARCH_HOSTS contains duplicate hostnames")
    return hosts


def _require_research_host(url: str, allowed_hosts: tuple[str, ...]) -> None:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
    except ValueError as exc:
        raise ResearchFetchError("Invalid source URL") from exc
    if parsed.scheme != "https" or host not in allowed_hosts:
        raise ResearchFetchError("Source URL must use HTTPS on a configured research host")


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str
    paragraphs: tuple[str, ...]
    response_status: int = 200
    retrieval_url: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs)

    def excerpt(self) -> dict:
        remaining = MAX_PROMPT_CHARS
        excerpts = []
        for index, paragraph in enumerate(self.paragraphs[:80], 1):
            if remaining <= 0:
                break
            shown = paragraph[: min(2000, remaining)]
            excerpts.append({"locator": f"paragraph {index}", "text": shown})
            remaining -= len(shown)
        return {
            "url": self.url,
            "title": self.title,
            "http_status": self.response_status,
            "retrieval_url": self.retrieval_url,
            "paragraphs": excerpts,
        }


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.hidden = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        elif tag == "title":
            self.in_title = True
        elif tag in {"p", "div", "article", "section", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag == "title":
            self.in_title = False
        elif tag in {"p", "div", "article", "section", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.hidden:
            return
        if self.in_title:
            self.title_parts.append(data)
        else:
            self.parts.append(data)


def _public_address(host: str, port: int) -> str:
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ResearchFetchError("The source host could not be resolved") from exc
    if not addresses or any(not addr.is_global for addr in addresses):
        raise ResearchFetchError("Source URLs must resolve only to public addresses")
    # Platform egress is IPv4-only; prefer it when DNS offers both families.
    return str(min(addresses, key=lambda addr: (addr.version != 4, int(addr))))


def _read(
    url: str, *, media_types: frozenset[str] = frozenset({"text/html", "text/plain"})
) -> tuple[str, str, bytes, int]:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError as exc:
        raise ResearchFetchError("Invalid source URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or len(url) > 2000
    ):
        raise ResearchFetchError("Only public HTTP or HTTPS URLs are supported")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ResearchFetchError("Invalid source URL port") from exc
    if port not in {80, 443}:
        raise ResearchFetchError("Source URL must use a standard web port")
    host = hostname.encode("idna").decode("ascii")
    address = _public_address(host, port)
    if parsed.scheme == "https":
        connection = http.client.HTTPSConnection(host, port, timeout=TIMEOUT_SECONDS)

        def connect() -> None:
            sock = socket.create_connection((address, port), TIMEOUT_SECONDS)
            connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)

    else:
        connection = http.client.HTTPConnection(host, port, timeout=TIMEOUT_SECONDS)

        def connect() -> None:
            connection.sock = socket.create_connection((address, port), TIMEOUT_SECONDS)

    connection.connect = connect
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    try:
        connection.request(
            "GET",
            path,
            headers={
                "User-Agent": "BotSocialResearch/1.0",
                "Accept": ", ".join(sorted(media_types)),
            },
        )
        response = connection.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")
            if not location:
                raise ResearchFetchError("Source redirect has no destination")
            return urljoin(url, location), "redirect", b"", response.status
        if response.status not in {200, 203}:
            raise ResearchFetchError(f"Source returned HTTP {response.status}")
        media_type = response.getheader("Content-Type", "").split(";", 1)[0].lower()
        if media_type not in media_types:
            raise ResearchFetchError("Source has an unsupported content type")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ResearchFetchError("Source page is too large")
        return (
            urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")),
            media_type,
            body,
            response.status,
        )
    except (OSError, http.client.HTTPException) as exc:
        raise ResearchFetchError("Source could not be fetched") from exc
    finally:
        connection.close()


def _pubmed_identifier(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        if parsed.port not in {None, 443}:
            return None
    except ValueError:
        return None
    match = PUBMED_ARTICLE_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != PUBMED_HOST
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        return None
    return match.group(1)


def _fetch_pubmed_abstract(pmid: str, allowed_hosts: tuple[str, ...] | None) -> FetchedPage:
    url = f"https://{PUBMED_API_HOST}/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
    for _ in range(MAX_REDIRECTS + 1):
        _require_research_host(url, (PUBMED_API_HOST,))
        if allowed_hosts is not None:
            _require_research_host(url, allowed_hosts)
        destination, media_type, body, status = _read(
            url, media_types=frozenset({"text/xml", "application/xml"})
        )
        if media_type == "redirect":
            url = destination
            continue
        if b"<!ENTITY" in body.upper():
            raise ResearchFetchError("PubMed response contains XML entities")
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as exc:
            raise ResearchFetchError("PubMed returned invalid XML") from exc
        articles = root.findall("./PubmedArticle") if root.tag == "PubmedArticleSet" else []
        if len(articles) != 1:
            raise ResearchFetchError("PubMed did not return one article")
        citation = articles[0].find("./MedlineCitation")
        if citation is None or citation.findtext("PMID") != pmid:
            raise ResearchFetchError("PubMed returned a different article")
        article = citation.find("Article")
        if article is None:
            raise ResearchFetchError("PubMed article has no abstract")
        title_element = article.find("ArticleTitle")
        title = (
            " ".join("".join(title_element.itertext()).split()) if title_element is not None else ""
        )
        paragraphs = tuple(
            passage
            for element in article.findall("./Abstract/AbstractText")
            if (passage := " ".join("".join(element.itertext()).split()))
        )
        if not paragraphs:
            raise ResearchFetchError("PubMed article has no abstract")
        return FetchedPage(
            f"https://{PUBMED_HOST}/{pmid}/",
            (title or f"PubMed article {pmid}")[:300],
            paragraphs[:200],
            status,
            destination,
        )
    raise ResearchFetchError("PubMed API redirected too many times")


def fetch_page(url: str, allowed_hosts: tuple[str, ...] | None = None) -> FetchedPage:
    if pmid := _pubmed_identifier(url):
        if allowed_hosts is not None:
            _require_research_host(url, allowed_hosts)
        return _fetch_pubmed_abstract(pmid, allowed_hosts)
    for _ in range(MAX_REDIRECTS + 1):
        if allowed_hosts is not None:
            _require_research_host(url, allowed_hosts)
        destination, media_type, body, response_status = _read(url)
        if media_type != "redirect":
            text = body.decode("utf-8", errors="replace")
            if media_type == "text/html":
                parser = _TextParser()
                parser.feed(text)
                title = (
                    " ".join(parser.title_parts).strip()
                    or urlsplit(destination).hostname
                    or destination
                )
                lines = "".join(parser.parts).splitlines()
            else:
                title = urlsplit(destination).hostname or destination
                lines = text.splitlines()
            paragraphs = tuple(
                normalized for line in lines if (normalized := re.sub(r"\s+", " ", line).strip())
            )
            if not paragraphs:
                raise ResearchFetchError("Source page contains no readable text")
            if (
                response_status == 203
                and urlsplit(destination).hostname == PUBMED_HOST
                and any("Cookies must be enabled" in item for item in paragraphs[:5])
            ):
                raise ResearchFetchError("PubMed returned a cookie challenge instead of an article")
            return FetchedPage(destination, title[:300], paragraphs[:200], response_status)
        url = destination
    raise ResearchFetchError("Source redirected too many times")
