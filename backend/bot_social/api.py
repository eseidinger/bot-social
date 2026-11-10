import json
import os
from datetime import datetime
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from opentelemetry import trace
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Case, Evidence, Finding, Job, Post, Source, Subclaim, Verdict, now
from .telemetry import configure_tracing
from .workflow import enqueue

SessionDep = Annotated[Session, Depends(get_session)]


async def roles(
    group_names: Annotated[str | None, Header(alias="X-Platform-Principal-Group-Names")] = None,
) -> list[str]:
    moderator_group_name = os.getenv("MODERATOR_GROUP_NAME")
    if moderator_group_name and moderator_group_name in (group_names or "").split():
        return ["moderator"]
    return []


RolesDep = Annotated[list[str], Depends(roles)]


def moderator(current_roles: RolesDep) -> None:
    if "moderator" not in current_roles:
        raise HTTPException(403, "Moderator role required")


ModeratorDep = Annotated[None, Depends(moderator)]


class ClaimIn(BaseModel):
    claim: str = Field(min_length=10, max_length=5000)
    source_url: str | None = Field(default=None, max_length=2000)
    source_title: str | None = Field(default=None, max_length=300)
    source_text: str | None = Field(default=None, max_length=20000)

    @field_validator("claim")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Claim must not be blank")
        return value.strip()

    @field_validator("source_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("A source URL must be HTTP or HTTPS")
        return value


class EvidenceIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    original_source_id: str | None = None
    passage: str = Field(min_length=1, max_length=20000)
    locator: str = Field(min_length=1, max_length=300)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        return ClaimIn.valid_url(value)

    @field_validator("title", "passage", "locator")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Evidence fields must not be blank")
        return value.strip()


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


class VerdictEditIn(TextIn):
    evidence_ids: list[str]


class CaseSummary(BaseModel):
    id: str
    claim: str
    source_url: str | None
    status: str
    created_at: datetime


class SubclaimOut(BaseModel):
    id: str
    text: str


class SourceOut(BaseModel):
    id: str
    title: str
    url: str | None
    original_source_id: str | None


class EvidenceOut(BaseModel):
    id: str
    source_id: str
    passage: str
    locator: str
    captured_at: datetime


class FindingOut(BaseModel):
    id: str
    subclaim_id: str
    evidence_id: str
    assessment: str
    rationale: str


class VerdictOut(BaseModel):
    id: str
    revision: int
    status: str
    text: str
    evidence_ids: list[str]
    created_at: datetime
    published_at: datetime | None


class PostOut(BaseModel):
    id: str
    kind: str
    text: str
    created_at: datetime


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    attempts: int
    error: str | None


class CaseDetail(CaseSummary):
    subclaims: list[SubclaimOut]
    sources: list[SourceOut]
    evidence: list[EvidenceOut]
    findings: list[FindingOut]
    verdicts: list[VerdictOut]
    posts: list[PostOut]
    jobs: list[JobOut]


app = FastAPI(title="Bot Social", version="0.1.0")
configure_tracing("bot-social-api")


@app.middleware("http")
async def trace_request(request, call_next):
    with trace.get_tracer("bot_social.api").start_as_current_span("http.request") as span:
        span.set_attribute("http.request.method", request.method)
        span.set_attribute("url.path", request.url.path)
        response = await call_next(request)
        span.set_attribute("http.response.status_code", response.status_code)
        return response


def require_case(session: Session, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


def case_detail(session: Session, case: Case) -> CaseDetail:
    def rows(model):
        return session.scalars(select(model).where(model.case_id == case.id)).all()

    return CaseDetail(
        id=case.id,
        claim=case.claim,
        source_url=case.source_url,
        status=case.status,
        created_at=case.created_at,
        subclaims=[SubclaimOut(id=x.id, text=x.text) for x in rows(Subclaim)],
        sources=[
            SourceOut(id=x.id, title=x.title, url=x.url, original_source_id=x.original_source_id)
            for x in rows(Source)
        ],
        evidence=[
            EvidenceOut(
                id=x.id,
                source_id=x.source_id,
                passage=x.passage,
                locator=x.locator,
                captured_at=x.captured_at,
            )
            for x in rows(Evidence)
        ],
        findings=[
            FindingOut(
                id=x.id,
                subclaim_id=x.subclaim_id,
                evidence_id=x.evidence_id,
                assessment=x.assessment,
                rationale=x.rationale,
            )
            for x in rows(Finding)
        ],
        verdicts=[
            VerdictOut(
                id=x.id,
                revision=x.revision,
                status=x.status,
                text=x.text,
                evidence_ids=json.loads(x.evidence_ids),
                created_at=x.created_at,
                published_at=x.published_at,
            )
            for x in sorted(rows(Verdict), key=lambda v: v.revision)
        ],
        posts=[
            PostOut(id=x.id, kind=x.kind, text=x.text, created_at=x.created_at)
            for x in sorted(rows(Post), key=lambda p: p.created_at)
        ],
        jobs=[
            JobOut(id=x.id, kind=x.kind, status=x.status, attempts=x.attempts, error=x.error)
            for x in sorted(rows(Job), key=lambda j: j.created_at)
        ],
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/roles", response_model=list[str])
async def get_roles(current_roles: RolesDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return current_roles


@app.post("/api/cases", response_model=CaseSummary, status_code=201)
def create_case(payload: ClaimIn, session: SessionDep):
    case = Case(claim=payload.claim, source_url=payload.source_url)
    session.add(case)
    session.flush()
    session.add(Post(case_id=case.id, kind="submission", text=payload.claim))
    if payload.source_text and payload.source_text.strip():
        session.add(
            Source(
                case_id=case.id,
                title=(payload.source_title or "").strip() or "Submitted source",
                url=payload.source_url,
                content=payload.source_text.strip(),
            )
        )
    enqueue(session, case.id, "research")
    session.commit()
    return case


@app.get("/api/cases", response_model=list[CaseSummary])
def list_cases(session: SessionDep, q: Annotated[str | None, Query(max_length=200)] = None):
    query = select(Case)
    if q:
        if session.bind.dialect.name == "postgresql":
            passage_match = select(Evidence.case_id).where(
                func.to_tsvector("english", Evidence.passage).op("@@")(
                    func.plainto_tsquery("english", q)
                )
            )
            query = query.where(
                or_(
                    func.to_tsvector("english", Case.claim).op("@@")(
                        func.plainto_tsquery("english", q)
                    ),
                    Case.id.in_(passage_match),
                )
            )
        else:
            query = query.where(
                or_(
                    Case.claim.ilike(f"%{q}%"),
                    Case.id.in_(select(Evidence.case_id).where(Evidence.passage.ilike(f"%{q}%"))),
                )
            )
    return session.scalars(query.order_by(Case.created_at.desc()).limit(100)).all()


@app.get("/api/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, session: SessionDep):
    return case_detail(session, require_case(session, case_id))


@app.post("/api/cases/{case_id}/objections", response_model=CaseDetail, status_code=201)
def add_objection(case_id: str, payload: TextIn, session: SessionDep):
    case = require_case(session, case_id)
    session.add(Post(case_id=case.id, kind="objection", text=payload.text.strip()))
    session.commit()
    return case_detail(session, case)


@app.post("/api/cases/{case_id}/evidence", response_model=CaseDetail, status_code=201)
def add_evidence(case_id: str, payload: EvidenceIn, session: SessionDep, _: ModeratorDep):
    case = require_case(session, case_id)
    if payload.original_source_id:
        original = session.get(Source, payload.original_source_id)
        if original is None or original.case_id != case.id:
            raise HTTPException(422, "Original source must belong to this case")
    source = Source(
        case_id=case.id,
        title=payload.title.strip(),
        url=payload.url,
        original_source_id=payload.original_source_id,
    )
    session.add(source)
    session.flush()
    session.add(
        Evidence(
            case_id=case.id,
            source_id=source.id,
            passage=payload.passage.strip(),
            locator=payload.locator.strip(),
        )
    )
    session.commit()
    return case_detail(session, case)


@app.post("/api/cases/{case_id}/review", response_model=CaseDetail)
def start_review(case_id: str, session: SessionDep, _: ModeratorDep):
    case = require_case(session, case_id)
    if not session.scalar(select(Evidence).where(Evidence.case_id == case.id).limit(1)):
        raise HTTPException(409, "Add evidence before review")
    if not session.scalar(select(Subclaim).where(Subclaim.case_id == case.id).limit(1)):
        raise HTTPException(409, "Research must finish before review")
    active = session.scalar(
        select(Job).where(Job.case_id == case.id, Job.status.in_(["pending", "running"])).limit(1)
    )
    if active:
        raise HTTPException(409, "A job is already active")
    for draft in session.scalars(
        select(Verdict).where(Verdict.case_id == case.id, Verdict.status == "draft")
    ).all():
        session.delete(draft)
    enqueue(session, case.id, "review")
    case.status = "reviewing"
    session.commit()
    return case_detail(session, case)


@app.post("/api/sources/{source_id}/corrections", response_model=list[CaseSummary])
def correct_source(source_id: str, payload: TextIn, session: SessionDep, _: ModeratorDep):
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    # Traverse repeated URLs and explicit derivation links. PostgreSQL remains
    # authoritative; no graph projection is needed for this MVP operation.
    affected_ids = {source.id}
    if source.url:
        affected_ids.update(session.scalars(select(Source.id).where(Source.url == source.url)))
    while True:
        children = set(
            session.scalars(select(Source.id).where(Source.original_source_id.in_(affected_ids)))
        )
        expanded = affected_ids | children
        if expanded == affected_ids:
            break
        affected_ids = expanded
    evidence_by_case: dict[str, set[str]] = {}
    for evidence in session.scalars(select(Evidence).where(Evidence.source_id.in_(affected_ids))):
        evidence_by_case.setdefault(evidence.case_id, set()).add(evidence.id)
    affected_cases = []
    for case_id, evidence_ids in evidence_by_case.items():
        verdicts = session.scalars(
            select(Verdict).where(Verdict.case_id == case_id, Verdict.status == "published")
        )
        if not any(evidence_ids.intersection(json.loads(v.evidence_ids)) for v in verdicts):
            continue
        case = session.get(Case, case_id)
        case.status = "needs_review"
        session.add(
            Post(
                case_id=case_id,
                kind="source_correction",
                text=f"A cited source was corrected: {payload.text.strip()}",
            )
        )
        affected_cases.append(case)
    session.commit()
    return affected_cases


@app.put("/api/cases/{case_id}/verdicts/{verdict_id}", response_model=CaseDetail)
def edit_verdict(
    case_id: str, verdict_id: str, payload: VerdictEditIn, session: SessionDep, _: ModeratorDep
):
    case = require_case(session, case_id)
    verdict = session.get(Verdict, verdict_id)
    if verdict is None or verdict.case_id != case.id:
        raise HTTPException(404, "Verdict not found")
    if verdict.status != "draft":
        raise HTTPException(409, "Published verdicts are immutable")
    valid = set(session.scalars(select(Evidence.id).where(Evidence.case_id == case.id)))
    if not set(payload.evidence_ids).issubset(valid):
        raise HTTPException(422, "Verdict references evidence outside this case")
    verdict.text = payload.text.strip()
    verdict.evidence_ids = json.dumps(list(dict.fromkeys(payload.evidence_ids)))
    session.commit()
    return case_detail(session, case)


@app.post("/api/cases/{case_id}/verdicts/{verdict_id}/publish", response_model=CaseDetail)
def publish_verdict(case_id: str, verdict_id: str, session: SessionDep, _: ModeratorDep):
    case = require_case(session, case_id)
    verdict = session.scalar(
        select(Verdict)
        .where(Verdict.id == verdict_id, Verdict.case_id == case.id)
        .with_for_update()
    )
    if verdict is None:
        raise HTTPException(404, "Verdict not found")
    if verdict.status != "draft":
        raise HTTPException(409, "Verdict already published")
    if not verdict.text.strip() or verdict.text.startswith(
        "Evidence has been collected. A moderator must"
    ):
        raise HTTPException(409, "Write a substantive verdict before publication")
    if not json.loads(verdict.evidence_ids):
        raise HTTPException(409, "Cite at least one evidence passage")
    verdict.status = "published"
    verdict.published_at = now()
    case.status = "published"
    session.add(
        Post(
            case_id=case.id,
            kind="publication",
            text=f"Verdict revision {verdict.revision} published.",
        )
    )
    session.commit()
    return case_detail(session, case)
