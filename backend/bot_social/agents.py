"""Bounded agent inputs and validated structured outputs.

With no model configured the workflow remains usable for moderator-led review.
It never fabricates research or a factual verdict in that mode.
"""

import json
import os

from opentelemetry import trace
from pydantic import BaseModel, Field
from pydantic_ai import Agent


class ResearchResult(BaseModel):
    subclaims: list[str] = Field(min_length=1, max_length=8)
    passages: list["ResearchPassage"] = Field(default_factory=list, max_length=8)


class ResearchPassage(BaseModel):
    quote: str
    locator: str


class Assessment(BaseModel):
    subclaim_id: str
    evidence_id: str
    assessment: str
    rationale: str


class ReviewResult(BaseModel):
    findings: list[Assessment]
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)


class EditorialResult(BaseModel):
    text: str
    evidence_ids: list[str]


def _run(role: str, instructions: str, prompt: dict, output_type: type[BaseModel]):
    model = os.getenv(f"BOT_SOCIAL_{role.upper()}_MODEL") or os.getenv("BOT_SOCIAL_MODEL")
    if not model:
        return None
    with trace.get_tracer("bot_social.agents").start_as_current_span(f"agent.{role}") as span:
        span.set_attribute("agent.role", role)
        return (
            Agent(model, instructions=instructions, output_type=output_type)
            .run_sync(json.dumps(prompt))
            .output
        )


def research(claim: str, source_url: str | None, source_text: str | None) -> ResearchResult:
    result = _run(
        "research",
        "Split the claim into at most eight independently testable subclaims. If submitted_source_text is present, select up to eight exact, relevant quotations copied verbatim from it, with a locator such as a paragraph or section. You have no browsing tool. Do not claim to have inspected a URL or invent sources or passages.",
        {"claim": claim, "submitted_url": source_url, "submitted_source_text": source_text},
        ResearchResult,
    )
    if result is None:
        passages = (
            [ResearchPassage(quote=source_text[:2000], locator="submitted text, opening excerpt")]
            if source_text
            else []
        )
        return ResearchResult(subclaims=[claim], passages=passages)
    if source_text is None and result.passages:
        raise ValueError("Research returned passages without source text")
    if source_text and any(
        p.quote not in source_text or not p.quote.strip() or not p.locator.strip()
        for p in result.passages
    ):
        raise ValueError("Research passage is not an exact quotation from submitted text")
    return result


def review(subclaims: list[dict], evidence: list[dict]) -> ReviewResult:
    result = _run(
        "review",
        "Assess only supplied passages. Each finding must use an exact subclaim_id and evidence_id from the input. assessment must be supports, undermines, or unclear. Explain limits. Do not infer independent corroboration from repeated reports. List specific unanswered questions in follow_up_questions so a moderator can request more research.",
        {"subclaims": subclaims, "evidence": evidence},
        ReviewResult,
    )
    if result is None:
        return ReviewResult(
            findings=[
                Assessment(
                    subclaim_id=s["id"],
                    evidence_id=e["id"],
                    assessment="unclear",
                    rationale="Awaiting moderator assessment; no review model is configured.",
                )
                for s in subclaims
                for e in evidence
            ]
        )
    valid_subclaims = {s["id"] for s in subclaims}
    valid_evidence = {e["id"] for e in evidence}
    for finding in result.findings:
        if (
            finding.subclaim_id not in valid_subclaims
            or finding.evidence_id not in valid_evidence
            or finding.assessment not in {"supports", "undermines", "unclear"}
        ):
            raise ValueError("Review output contains an invalid reference or assessment")
    return result


def editorial(
    claim: str, subclaims: list[dict], evidence: list[dict], findings: list[dict]
) -> EditorialResult:
    result = _run(
        "editorial",
        "Draft a cautious fact-check verdict using only the supplied evidence and findings. Cite evidence by ID in evidence_ids. If support is insufficient, say so. Do not fabricate sources or imply human approval.",
        {"claim": claim, "subclaims": subclaims, "evidence": evidence, "findings": findings},
        EditorialResult,
    )
    if result is None:
        return EditorialResult(
            text="Evidence has been collected. A moderator must assess the passages and write a verdict before publication.",
            evidence_ids=[e["id"] for e in evidence],
        )
    valid_evidence = {e["id"] for e in evidence}
    if not result.text.strip() or not set(result.evidence_ids).issubset(valid_evidence):
        raise ValueError("Editorial output contains invalid evidence references")
    return result
