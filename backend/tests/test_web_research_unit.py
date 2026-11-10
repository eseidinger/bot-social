import pytest

from bot_social import web_research


def test_fetch_page_extracts_exact_paragraphs_after_redirect(monkeypatch):
    responses = iter(
        [
            ("https://example.org/report", "redirect", b""),
            (
                "https://example.org/report",
                "text/html",
                b"<html><title>Motor report</title><script>ignore me</script>"
                b"<p>The motor stopped when the battery was removed.</p></html>",
            ),
        ]
    )
    monkeypatch.setattr(web_research, "_read", lambda url: next(responses))

    page = web_research.fetch_page("https://example.org/old")
    assert page.url == "https://example.org/report"
    assert page.title == "Motor report"
    assert page.paragraphs == ("The motor stopped when the battery was removed.",)
    assert page.excerpt()["paragraphs"] == [
        {"locator": "paragraph 1", "text": "The motor stopped when the battery was removed."}
    ]


@pytest.mark.parametrize("url", ["http://127.0.0.1/private", "http://[::1]/private"])
def test_fetch_page_rejects_private_ip_addresses(url):
    with pytest.raises(web_research.ResearchFetchError, match="public addresses"):
        web_research.fetch_page(url)


def test_fetch_page_rejects_redirect_to_private_address(monkeypatch):
    original = web_research._read
    monkeypatch.setattr(
        web_research,
        "_read",
        lambda url: (
            ("http://127.0.0.1/private", "redirect", b"")
            if url == "https://example.org/redirect"
            else original(url)
        ),
    )
    with pytest.raises(web_research.ResearchFetchError, match="public addresses"):
        web_research.fetch_page("https://example.org/redirect")


def test_fetch_page_rejects_non_web_ports():
    with pytest.raises(web_research.ResearchFetchError, match="standard web port"):
        web_research.fetch_page("http://example.org:2375/containers/json")


def test_prompt_excerpt_is_bounded():
    page = web_research.FetchedPage("https://example.org", "Large page", ("x" * 100_000,))
    assert len(page.excerpt()["paragraphs"][0]["text"]) == 2000


def test_dns_with_any_private_address_is_rejected(monkeypatch):
    monkeypatch.setattr(
        web_research.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (None, None, None, None, ("93.184.215.14", 443)),
            (None, None, None, None, ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(web_research.ResearchFetchError, match="public addresses"):
        web_research.fetch_page("https://example.org/report")


def test_read_bounded_public_html(monkeypatch):
    class Response:
        status = 200

        def getheader(self, name, default=None):
            return "text/html; charset=utf-8" if name == "Content-Type" else default

        def read(self, length):
            assert length == web_research.MAX_BYTES + 1
            return b"<p>A public report.</p>"

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("example.org", 80, web_research.TIMEOUT_SECONDS)

        def request(self, method, path, headers):
            assert (method, path) == ("GET", "/report")

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(web_research, "_public_address", lambda host, port: "93.184.215.14")
    monkeypatch.setattr(web_research.http.client, "HTTPConnection", Connection)
    page = web_research.fetch_page("http://example.org/report")
    assert page.paragraphs == ("A public report.",)
