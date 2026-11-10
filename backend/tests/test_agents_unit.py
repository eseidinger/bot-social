import json
from types import SimpleNamespace

import pytest
from pydantic_ai.native_tools import WebSearchTool

from bot_social import agents
from bot_social.web_research import FetchedPage, ResearchFetchError


@pytest.fixture
def no_model(monkeypatch):
    for name in (
        "BOT_SOCIAL_MODEL",
        "BOT_SOCIAL_RESEARCH_MODEL",
        "BOT_SOCIAL_REVIEW_MODEL",
        "BOT_SOCIAL_EDITORIAL_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_research_fallback_uses_only_submitted_text(no_model, monkeypatch):
    def unavailable(url):
        raise ResearchFetchError("Unavailable")

    monkeypatch.setattr(agents, "fetch_page", unavailable)
    source_text = "The motor stopped when the battery was removed."
    result = agents.research(
        "The motor runs without input.", "https://example.org/report", source_text
    )
    assert result.result.subclaims == ["The motor runs without input."]
    assert [(passage.quote, passage.locator) for passage in result.result.passages] == [
        (source_text, "submitted text, opening excerpt")
    ]
    assert (
        agents.research(
            "The motor runs without input.", "https://example.org/report", None
        ).result.passages
        == []
    )
    assert result.notes == ("Submitted URL could not be fetched: Unavailable",)


def test_research_rejects_fabricated_or_unattributed_passages(monkeypatch):
    monkeypatch.setattr(
        agents, "fetch_page", lambda url: (_ for _ in ()).throw(ResearchFetchError("Unavailable"))
    )
    passage = agents.ResearchPassage(quote="invented quote", locator="page 1")
    monkeypatch.setattr(
        agents,
        "_run",
        lambda *args, **kwargs: agents.ResearchResult(
            subclaims=["A test claim"], passages=[passage]
        ),
    )
    with pytest.raises(ValueError, match="exact quotation"):
        agents.research("A test claim", None, "The actual source text.")
    with pytest.raises(ValueError, match="submitted text"):
        agents.research("A test claim", "https://example.org", None)


def test_research_accepts_only_quotes_from_fetched_pages(monkeypatch):
    page = FetchedPage("https://example.org/report", "Test report", ("The motor stopped.",))
    monkeypatch.setattr(agents, "fetch_page", lambda url: page)
    passage = agents.ResearchPassage(
        source_url=page.url, quote="The motor stopped.", locator="paragraph 1"
    )
    monkeypatch.setattr(
        agents,
        "_run",
        lambda *args, **kwargs: agents.ResearchResult(
            subclaims=["A test claim"], passages=[passage]
        ),
    )
    outcome = agents.research("A test claim", page.url, None)
    assert outcome.result.passages == [passage]
    assert outcome.pages[page.url] == page

    passage.quote = "An invented conclusion."
    with pytest.raises(ValueError, match="fetched page"):
        agents.research("A test claim", page.url, None)
    passage.quote = "The motor stopped."
    passage.locator = "paragraph 2"
    with pytest.raises(ValueError, match="fetched page"):
        agents.research("A test claim", page.url, None)


def test_research_fetches_submitted_url_without_a_model(no_model, monkeypatch):
    page = FetchedPage("https://example.org/report", "Test report", ("The motor stopped.",))
    monkeypatch.setattr(agents, "fetch_page", lambda url: page)
    outcome = agents.research("The motor runs forever.", page.url, None)
    assert outcome.result.passages == [
        agents.ResearchPassage(
            source_url=page.url, quote="The motor stopped.", locator="paragraph 1"
        )
    ]


def test_research_agent_can_open_a_discovered_page(monkeypatch):
    page = FetchedPage("https://example.org/study", "Study", ("The measured output was zero.",))
    monkeypatch.setattr(agents, "fetch_page", lambda url: page)
    monkeypatch.setenv("BOT_SOCIAL_RESEARCH_MODEL", "openai:test")

    class FakeAgent:
        def __init__(self, model, *, instructions, output_type, tools, capabilities):
            self.open_page = tools[0]

        def run_sync(self, prompt, **kwargs):
            opened = self.open_page(page.url)
            assert opened["paragraphs"][0]["text"] == page.paragraphs[0]
            return SimpleNamespace(
                output=agents.ResearchResult(
                    subclaims=["The device produces output."],
                    passages=[
                        agents.ResearchPassage(
                            source_url=page.url,
                            quote=page.paragraphs[0],
                            locator="paragraph 1",
                        )
                    ],
                )
            )

    monkeypatch.setattr(agents, "Agent", FakeAgent)
    outcome = agents.research("The device produces output.", None, None)
    assert outcome.pages == {page.url: page}
    assert outcome.result.passages[0].source_url == page.url


def test_review_fallback_marks_each_pair_unclear(no_model):
    result = agents.review(
        [{"id": "claim-1"}, {"id": "claim-2"}],
        [{"id": "evidence-1"}],
    )
    assert {(item.subclaim_id, item.evidence_id, item.assessment) for item in result.findings} == {
        ("claim-1", "evidence-1", "unclear"),
        ("claim-2", "evidence-1", "unclear"),
    }
    assert result.follow_up_questions == []


def test_review_accepts_a_cited_finding_and_follow_up_question(monkeypatch):
    expected = agents.ReviewResult(
        findings=[
            agents.Assessment(
                subclaim_id="claim-1",
                evidence_id="evidence-1",
                assessment="undermines",
                rationale="The report describes a battery input.",
            )
        ],
        follow_up_questions=["Was the test independently repeated?"],
    )
    monkeypatch.setattr(agents, "_run", lambda *args: expected)
    result = agents.review([{"id": "claim-1"}], [{"id": "evidence-1"}])
    assert result == expected


@pytest.mark.parametrize(
    "subclaim_id,evidence_id,assessment",
    [
        ("unknown", "evidence-1", "supports"),
        ("claim-1", "unknown", "supports"),
        ("claim-1", "evidence-1", "certain"),
    ],
)
def test_review_rejects_invalid_findings(monkeypatch, subclaim_id, evidence_id, assessment):
    finding = agents.Assessment(
        subclaim_id=subclaim_id,
        evidence_id=evidence_id,
        assessment=assessment,
        rationale="Assessment from supplied material.",
    )
    monkeypatch.setattr(agents, "_run", lambda *args: agents.ReviewResult(findings=[finding]))
    with pytest.raises(ValueError, match="invalid reference or assessment"):
        agents.review([{"id": "claim-1"}], [{"id": "evidence-1"}])


def test_editorial_fallback_and_reference_guard(monkeypatch):
    evidence = [{"id": "evidence-1"}]
    monkeypatch.setattr(agents, "_run", lambda *args: None)
    fallback = agents.editorial("Claim", [], evidence, [])
    assert fallback.evidence_ids == ["evidence-1"]
    assert "moderator" in fallback.text.lower()

    monkeypatch.setattr(
        agents,
        "_run",
        lambda *args: agents.EditorialResult(text="A verdict", evidence_ids=["invented-evidence"]),
    )
    with pytest.raises(ValueError, match="invalid evidence references"):
        agents.editorial("Claim", [], evidence, [])


def test_research_model_override(monkeypatch):
    selected_models = []
    prompts = []

    class FakeAgent:
        def __init__(self, model, *, instructions, output_type, tools, capabilities):
            selected_models.append(model)
            assert output_type is agents.ResearchResult
            assert "exact" in instructions
            assert len(tools) == 1
            assert len(capabilities) == 1
            assert isinstance(capabilities[0].native, WebSearchTool)
            assert capabilities[0].native.max_uses is None

        def run_sync(self, prompt, **kwargs):
            assert kwargs["usage_limits"].request_limit == 10
            prompts.append(json.loads(prompt))
            return SimpleNamespace(
                output=agents.ResearchResult(subclaims=["The motor needs power."])
            )

    monkeypatch.setattr(agents, "Agent", FakeAgent)
    monkeypatch.setenv("BOT_SOCIAL_MODEL", "openai:shared")
    monkeypatch.setenv("BOT_SOCIAL_RESEARCH_MODEL", "openai:research")

    agents.research("The motor runs without input.", None, None)
    monkeypatch.delenv("BOT_SOCIAL_RESEARCH_MODEL")
    agents.research("The motor runs without input.", None, None)

    assert selected_models == ["openai:research", "openai:shared"]
    assert len(prompts) == 2
