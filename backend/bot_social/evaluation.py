"""Fixed-source agent evaluations; never fetches a URL or invokes web search."""

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EvaluatorContext
from pydantic_evals.reporting import EvaluationReport

from . import agents


class FixedCase(BaseModel):
    id: str
    claim: str
    source_text: str
    expected_quote: str
    expected_assessment: Literal["supports", "undermines", "unclear"]
    expect_follow_up: bool = False
    forbidden_conclusions: list[str] = Field(default_factory=list)
    uncertainty_terms: list[str] = Field(default_factory=list)
    evaluation_mode: Literal["pipeline", "baseline"] = "pipeline"

    @model_validator(mode="after")
    def check_reference(self) -> "FixedCase":
        if not self.id.strip() or not self.claim.strip() or not self.source_text.strip():
            raise ValueError("Evaluation ID, claim, and source text must be nonempty")
        if not self.expected_quote or self.expected_quote not in self.source_text:
            raise ValueError("Expected quote must occur exactly in source text")
        if self.expected_assessment == "unclear" and not self.uncertainty_terms:
            raise ValueError("Unclear cases need uncertainty terms")
        return self


class EvalFinding(BaseModel):
    quote: str
    assessment: str


class EvalOutput(BaseModel):
    quotes: list[str]
    findings: list[EvalFinding]
    follow_up_questions: list[str]
    verdict_text: str
    cited_quotes: list[str]


class BaselineFinding(BaseModel):
    quote: str
    assessment: Literal["supports", "undermines", "unclear"]
    rationale: str


class BaselineResult(BaseModel):
    subclaims: list[str] = Field(min_length=1, max_length=8)
    quotes: list[str] = Field(max_length=8)
    findings: list[BaselineFinding]
    follow_up_questions: list[str] = Field(max_length=5)
    verdict_text: str
    cited_quotes: list[str]


def load_cases(path: Path) -> list[FixedCase]:
    cases = TypeAdapter(list[FixedCase]).validate_json(path.read_text())
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("Evaluation dataset must contain cases with unique IDs")
    return cases


def run_pipeline(case: FixedCase) -> EvalOutput:
    research = agents.research(case.claim, None, case.source_text, allow_web_search=False).result
    subclaims = [{"id": f"subclaim-{i}", "text": text} for i, text in enumerate(research.subclaims)]
    evidence = [
        {
            "id": f"evidence-{i}",
            "passage": passage.quote,
            "locator": passage.locator,
            "source_title": "Fixed source",
            "source_url": None,
        }
        for i, passage in enumerate(research.passages)
    ]
    review = agents.review(subclaims, evidence) if evidence else agents.ReviewResult(findings=[])
    findings = [item.model_dump() for item in review.findings]
    editorial = agents.editorial(case.claim, subclaims, evidence, findings)
    quotes = {item["id"]: item["passage"] for item in evidence}
    return EvalOutput(
        quotes=list(quotes.values()),
        findings=[
            EvalFinding(quote=quotes[item.evidence_id], assessment=item.assessment)
            for item in review.findings
        ],
        follow_up_questions=review.follow_up_questions,
        verdict_text=editorial.text,
        cited_quotes=[quotes[evidence_id] for evidence_id in editorial.evidence_ids],
    )


def run_baseline(case: FixedCase) -> EvalOutput:
    result = agents._run(
        "baseline",
        "In one pass, split the claim into testable subclaims, quote only exact text from the supplied source, assess how each quote bears on the claim, ask follow-up questions where evidence is insufficient, and draft a cautious verdict. Use only the supplied text. Every finding and citation must refer to a quote in quotes. Never search the web or imply human approval.",
        {"claim": case.claim, "submitted_source_text": case.source_text},
        BaselineResult,
    )
    if result is None:
        raise RuntimeError(
            "Set BOT_SOCIAL_BASELINE_MODEL or BOT_SOCIAL_MODEL for baseline evaluation"
        )
    if any(not quote.strip() or quote not in case.source_text for quote in result.quotes):
        raise ValueError("Baseline returned a quote absent from the fixed source")
    if any(item.quote not in result.quotes for item in result.findings):
        raise ValueError("Baseline finding references an unselected quote")
    if any(quote not in result.quotes for quote in result.cited_quotes):
        raise ValueError("Baseline verdict references an unselected quote")
    return EvalOutput(
        quotes=result.quotes,
        findings=[
            EvalFinding(quote=item.quote, assessment=item.assessment) for item in result.findings
        ],
        follow_up_questions=result.follow_up_questions,
        verdict_text=result.verdict_text,
        cited_quotes=result.cited_quotes,
    )


async def expected_quote_found(ctx: EvaluatorContext[FixedCase, EvalOutput]) -> bool:
    return ctx.inputs.expected_quote in ctx.output.quotes


async def quotes_are_grounded(ctx: EvaluatorContext[FixedCase, EvalOutput]) -> bool:
    return all(quote.strip() and quote in ctx.inputs.source_text for quote in ctx.output.quotes)


async def assessment_matches(ctx: EvaluatorContext[FixedCase, EvalOutput]) -> bool:
    return any(
        finding.quote == ctx.inputs.expected_quote
        and finding.assessment == ctx.inputs.expected_assessment
        for finding in ctx.output.findings
    )


async def verdict_cites_expected_quote(ctx: EvaluatorContext[FixedCase, EvalOutput]) -> bool:
    return ctx.inputs.expected_quote in ctx.output.cited_quotes and all(
        quote in ctx.output.quotes for quote in ctx.output.cited_quotes
    )


async def avoids_known_unsupported_conclusions(
    ctx: EvaluatorContext[FixedCase, EvalOutput],
) -> bool:
    text = ctx.output.verdict_text.casefold()
    return all(phrase.casefold() not in text for phrase in ctx.inputs.forbidden_conclusions)


async def handles_uncertainty(ctx: EvaluatorContext[FixedCase, EvalOutput]) -> bool:
    if ctx.inputs.expected_assessment != "unclear":
        return True
    text = ctx.output.verdict_text.casefold()
    return any(term.casefold() in text for term in ctx.inputs.uncertainty_terms)


async def asks_for_follow_up(ctx: EvaluatorContext[FixedCase, EvalOutput]) -> bool:
    return not ctx.inputs.expect_follow_up or any(
        question.strip() for question in ctx.output.follow_up_questions
    )


def build_dataset(
    cases: list[FixedCase], mode: Literal["pipeline", "baseline", "both"] = "pipeline"
) -> Dataset[FixedCase, EvalOutput, None]:
    modes = ("pipeline", "baseline") if mode == "both" else (mode,)
    return Dataset(
        name="bot-social-fixed-sources-v1",
        cases=[
            Case(
                name=f"{selected_mode}:{case.id}",
                inputs=case.model_copy(update={"evaluation_mode": selected_mode}),
            )
            for selected_mode in modes
            for case in cases
        ],
        evaluators=[
            expected_quote_found,
            quotes_are_grounded,
            assessment_matches,
            verdict_cites_expected_quote,
            avoids_known_unsupported_conclusions,
            handles_uncertainty,
            asks_for_follow_up,
        ],
    )


def summarize(report: EvaluationReport[FixedCase, EvalOutput, None]) -> dict[str, object]:
    return {
        "experiment": report.name,
        "dataset": report.dataset_name,
        "cases": [
            {
                "name": case.name,
                "assertions": {name: result.value for name, result in case.assertions.items()},
                "output": case.output.model_dump(),
            }
            for case in report.cases
        ],
        "failures": [
            {"name": failure.name, "error": failure.error_message} for failure in report.failures
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate agents on fixed source text")
    parser.add_argument(
        "--dataset", type=Path, default=Path(__file__).resolve().parents[1] / "evals/cases.json"
    )
    parser.add_argument("--mode", choices=("pipeline", "baseline", "both"), default="both")
    parser.add_argument("--output", type=Path, help="Write a machine-readable comparison report")
    args = parser.parse_args()
    pipeline_ready = bool(os.getenv("BOT_SOCIAL_MODEL")) or all(
        os.getenv(f"BOT_SOCIAL_{role}_MODEL") for role in ("RESEARCH", "REVIEW", "EDITORIAL")
    )
    baseline_ready = bool(os.getenv("BOT_SOCIAL_MODEL") or os.getenv("BOT_SOCIAL_BASELINE_MODEL"))
    if args.mode in ("pipeline", "both") and not pipeline_ready:
        parser.error("Configure BOT_SOCIAL_MODEL or all three role models before evaluating")
    if args.mode in ("baseline", "both") and not baseline_ready:
        parser.error(
            "Configure BOT_SOCIAL_MODEL or BOT_SOCIAL_BASELINE_MODEL for baseline evaluation"
        )
    dataset = build_dataset(load_cases(args.dataset), args.mode)

    async def evaluate_case(case: FixedCase) -> EvalOutput:
        task = run_pipeline if case.evaluation_mode == "pipeline" else run_baseline
        # Agent.run_sync needs its own thread because Pydantic Evals runs an event loop.
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(task, case).result()

    report = dataset.evaluate_sync(
        evaluate_case, name=f"fixed-source-{args.mode}", max_concurrency=1, progress=False
    )
    report.print(include_reasons=True)
    summary = summarize(report)
    reports = {
        mode: {
            "experiment": mode,
            "dataset": summary["dataset"],
            "cases": [case for case in summary["cases"] if case["name"].startswith(f"{mode}:")],
            "failures": [
                failure for failure in summary["failures"] if failure["name"].startswith(f"{mode}:")
            ],
        }
        for mode in (("pipeline", "baseline") if args.mode == "both" else (args.mode,))
    }
    if args.output:
        args.output.write_text(
            json.dumps(
                {
                    "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                    "agent_code_sha256": hashlib.sha256(
                        Path(agents.__file__).read_bytes() + Path(__file__).read_bytes()
                    ).hexdigest(),
                    "models": {
                        role.lower(): os.getenv(f"BOT_SOCIAL_{role}_MODEL")
                        or os.getenv("BOT_SOCIAL_MODEL")
                        for role in ("RESEARCH", "REVIEW", "EDITORIAL", "BASELINE")
                    },
                    "reports": reports,
                },
                indent=2,
            )
            + "\n"
        )
    if report.failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
