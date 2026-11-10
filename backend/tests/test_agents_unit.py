import json
from types import SimpleNamespace

import pytest

from bot_social import agents


@pytest.fixture
def no_model(monkeypatch):
    for name in (
        "BOT_SOCIAL_MODEL",
        "BOT_SOCIAL_RESEARCH_MODEL",
        "BOT_SOCIAL_REVIEW_MODEL",
        "BOT_SOCIAL_EDITORIAL_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_research_fallback_uses_only_submitted_text(no_model):
    source_text = "The motor stopped when the battery was removed."
    result = agents.research(
        "The motor runs without input.", "https://example.org/report", source_text
    )
    assert result.subclaims == ["The motor runs without input."]
    assert [(passage.quote, passage.locator) for passage in result.passages] == [
        (source_text, "submitted text, opening excerpt")
    ]
    assert (
        agents.research(
            "The motor runs without input.", "https://example.org/report", None
        ).passages
        == []
    )


def test_research_rejects_fabricated_or_unattributed_passages(monkeypatch):
    passage = agents.ResearchPassage(quote="invented quote", locator="page 1")
    monkeypatch.setattr(
        agents,
        "_run",
        lambda *args: agents.ResearchResult(subclaims=["A test claim"], passages=[passage]),
    )
    with pytest.raises(ValueError, match="exact quotation"):
        agents.research("A test claim", None, "The actual source text.")
    with pytest.raises(ValueError, match="without source text"):
        agents.research("A test claim", "https://example.org", None)


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
        def __init__(self, model, *, instructions, output_type):
            selected_models.append(model)
            assert output_type is agents.ResearchResult
            assert "exact" in instructions

        def run_sync(self, prompt):
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
