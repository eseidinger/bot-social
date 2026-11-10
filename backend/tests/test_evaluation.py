import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("pydantic_evals")

from bot_social import agents, evaluation
from bot_social.evaluation import (
    BaselineFinding,
    BaselineResult,
    EvalFinding,
    EvalOutput,
    FixedCase,
    build_dataset,
    load_cases,
    run_baseline,
    run_pipeline,
    summarize,
)


def test_dataset_has_valid_fixed_sources():
    cases = load_cases(Path(__file__).resolve().parents[1] / "evals/cases.json")
    assert len(cases) == 3
    assert {case.expected_assessment for case in cases} == {"supports", "undermines", "unclear"}


def test_dataset_rejects_missing_quote_and_duplicate_ids(tmp_path):
    item = {
        "id": "same",
        "claim": "The test claim",
        "source_text": "The source text.",
        "expected_quote": "Missing quote",
        "expected_assessment": "supports",
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([item]))
    with pytest.raises(ValueError, match="Expected quote"):
        load_cases(path)
    item["expected_quote"] = "The source text."
    path.write_text(json.dumps([item, item]))
    with pytest.raises(ValueError, match="unique IDs"):
        load_cases(path)


def test_pipeline_uses_fixed_text_without_web_tools(monkeypatch):
    case = FixedCase(
        id="example",
        claim="The motor runs without power.",
        source_text="The motor stopped when the battery was removed.",
        expected_quote="The motor stopped when the battery was removed.",
        expected_assessment="undermines",
    )
    calls = []

    def fake_run(role, _instructions, _prompt, _output_type, *, tools=(), capabilities=()):
        calls.append((role, tools, capabilities))
        if role == "research":
            return agents.ResearchResult(
                subclaims=[case.claim],
                passages=[
                    agents.ResearchPassage(
                        quote=case.expected_quote, locator="submitted text, sentence 1"
                    )
                ],
            )
        if role == "review":
            return agents.ReviewResult(
                findings=[
                    agents.Assessment(
                        subclaim_id="subclaim-0",
                        evidence_id="evidence-0",
                        assessment="undermines",
                        rationale="It stopped.",
                    )
                ]
            )
        return agents.EditorialResult(
            text="The test undermines the claim.", evidence_ids=["evidence-0"]
        )

    monkeypatch.setattr(agents, "_run", fake_run)
    monkeypatch.setattr(
        agents, "fetch_page", lambda *_: pytest.fail("Fixed-source evaluation fetched a URL")
    )
    output = run_pipeline(case)
    assert output.cited_quotes == [case.expected_quote]
    assert output.findings == [EvalFinding(quote=case.expected_quote, assessment="undermines")]
    assert [role for role, _, _ in calls] == ["research", "review", "editorial"]
    assert all(not tools and not capabilities for _, tools, capabilities in calls)


def test_baseline_rejects_unattributed_quotes(monkeypatch):
    case = FixedCase(
        id="example",
        claim="The motor runs without power.",
        source_text="The motor stopped.",
        expected_quote="The motor stopped.",
        expected_assessment="undermines",
    )
    monkeypatch.setattr(
        agents,
        "_run",
        lambda *args, **kwargs: BaselineResult(
            subclaims=[case.claim],
            quotes=["The motor ran forever."],
            findings=[
                BaselineFinding(
                    quote="The motor ran forever.", assessment="supports", rationale="Invented"
                )
            ],
            follow_up_questions=[],
            verdict_text="It ran forever.",
            cited_quotes=["The motor ran forever."],
        ),
    )
    with pytest.raises(ValueError, match="absent from the fixed source"):
        run_baseline(case)


def test_baseline_normalizes_a_grounded_result(monkeypatch):
    case = FixedCase(
        id="example",
        claim="The motor stopped.",
        source_text="The motor stopped.",
        expected_quote="The motor stopped.",
        expected_assessment="supports",
    )
    monkeypatch.setattr(
        agents,
        "_run",
        lambda *args, **kwargs: BaselineResult(
            subclaims=[case.claim],
            quotes=[case.expected_quote],
            findings=[
                BaselineFinding(
                    quote=case.expected_quote, assessment="supports", rationale="Exact match"
                )
            ],
            follow_up_questions=[],
            verdict_text="The source supports the claim.",
            cited_quotes=[case.expected_quote],
        ),
    )
    output = run_baseline(case)
    assert output.cited_quotes == [case.expected_quote]
    assert output.findings == [EvalFinding(quote=case.expected_quote, assessment="supports")]


def test_evaluators_expose_quality_failures():
    case = FixedCase(
        id="uncertain",
        claim="The filter removes every contaminant.",
        source_text="No other contaminants were measured.",
        expected_quote="No other contaminants were measured.",
        expected_assessment="unclear",
        expect_follow_up=True,
        forbidden_conclusions=["removes every contaminant"],
        uncertainty_terms=["insufficient"],
    )

    async def task(_case: FixedCase) -> EvalOutput:
        return EvalOutput(
            quotes=[case.expected_quote],
            findings=[EvalFinding(quote=case.expected_quote, assessment="supports")],
            follow_up_questions=[],
            verdict_text="The filter removes every contaminant.",
            cited_quotes=[case.expected_quote],
        )

    report = build_dataset([case]).evaluate_sync(task, progress=False)
    result = summarize(report)["cases"][0]["assertions"]
    assert result["expected_quote_found"] is True
    assert result["quotes_are_grounded"] is True
    assert result["assessment_matches"] is False
    assert result["avoids_known_unsupported_conclusions"] is False
    assert result["handles_uncertainty"] is False
    assert result["asks_for_follow_up"] is False


def test_cli_writes_comparable_reports_without_network(monkeypatch, tmp_path):
    case = FixedCase(
        id="offline",
        claim="The motor stopped.",
        source_text="The motor stopped.",
        expected_quote="The motor stopped.",
        expected_assessment="supports",
    )
    dataset_path = tmp_path / "cases.json"
    dataset_path.write_text(json.dumps([case.model_dump()]))
    report_path = tmp_path / "report.json"
    output = EvalOutput(
        quotes=[case.expected_quote],
        findings=[EvalFinding(quote=case.expected_quote, assessment="supports")],
        follow_up_questions=[],
        verdict_text="The source supports the claim.",
        cited_quotes=[case.expected_quote],
    )
    monkeypatch.setenv("BOT_SOCIAL_MODEL", "openai:test-model")
    monkeypatch.setattr(evaluation, "run_pipeline", lambda _: output)
    monkeypatch.setattr(evaluation, "run_baseline", lambda _: output)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluation",
            "--dataset",
            str(dataset_path),
            "--mode",
            "both",
            "--output",
            str(report_path),
        ],
    )
    evaluation.main()
    report = json.loads(report_path.read_text())
    assert len(report["dataset_sha256"]) == 64
    assert len(report["agent_code_sha256"]) == 64
    assert report["models"]["baseline"] == "openai:test-model"
    assert set(report["reports"]) == {"pipeline", "baseline"}
    assert report["reports"]["pipeline"]["cases"][0]["assertions"]["assessment_matches"]
