"""Bounded retrieval of public text pages for verifiable research passages."""

import http.client
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
MAX_PROMPT_CHARS = 16_000
TIMEOUT_SECONDS = 10


class ResearchFetchError(ValueError):
    """A page could not be safely used as research material."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str
    paragraphs: tuple[str, ...]

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
        addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ResearchFetchError("The source host could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
        raise ResearchFetchError("Source URLs must resolve only to public addresses")
    return sorted(addresses)[0]


def _read(url: str) -> tuple[str, str, bytes]:
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
            headers={"User-Agent": "BotSocialResearch/1.0", "Accept": "text/html, text/plain"},
        )
        response = connection.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")
            if not location:
                raise ResearchFetchError("Source redirect has no destination")
            return urljoin(url, location), "redirect", b""
        if response.status != 200:
            raise ResearchFetchError(f"Source returned HTTP {response.status}")
        media_type = response.getheader("Content-Type", "").split(";", 1)[0].lower()
        if media_type not in {"text/html", "text/plain"}:
            raise ResearchFetchError("Source is not an HTML or plain-text page")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ResearchFetchError("Source page is too large")
        return (
            urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")),
            media_type,
            body,
        )
    except (OSError, http.client.HTTPException) as exc:
        raise ResearchFetchError("Source could not be fetched") from exc
    finally:
        connection.close()


def fetch_page(url: str) -> FetchedPage:
    for _ in range(MAX_REDIRECTS + 1):
        destination, media_type, body = _read(url)
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
            return FetchedPage(destination, title[:300], paragraphs[:200])
        url = destination
    raise ResearchFetchError("Source redirected too many times")
