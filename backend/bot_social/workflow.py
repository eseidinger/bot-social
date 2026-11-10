"""Durable job processing; each job writes its result and next job atomically."""

import json
import time
from datetime import timedelta, timezone

from opentelemetry import propagate, trace
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import agents
from .db import SessionLocal
from .models import Case, Evidence, Finding, Job, Post, Source, Subclaim, Verdict, now

LEASE_SECONDS = 300
MAX_ATTEMPTS = 3


def enqueue(session: Session, case_id: str, kind: str) -> Job:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    job = Job(case_id=case_id, kind=kind, traceparent=carrier.get("traceparent"))
    session.add(job)
    return job


def claim_job(session: Session) -> str | None:
    for exhausted in session.scalars(
        select(Job)
        .where(Job.status == "running", Job.lease_until < now(), Job.attempts >= MAX_ATTEMPTS)
        .with_for_update(skip_locked=True)
    ):
        exhausted.status = "failed"
        exhausted.error = "Worker lease expired after the final attempt"
        exhausted.lease_until = None
    candidate = session.scalar(
        select(Job)
        .where(
            or_(Job.status == "pending", (Job.status == "running") & (Job.lease_until < now())),
            Job.attempts < MAX_ATTEMPTS,
        )
        .order_by(Job.created_at, Job.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if candidate is None:
        session.commit()
        return None
    candidate.status = "running"
    candidate.attempts += 1
    candidate.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
    session.commit()
    return candidate.id


def _snapshot(session: Session, case_id: str):
    case = session.get(Case, case_id)
    subclaims = [
        {"id": x.id, "text": x.text}
        for x in session.scalars(select(Subclaim).where(Subclaim.case_id == case_id))
    ]
    evidence = []
    for x in session.scalars(select(Evidence).where(Evidence.case_id == case_id)):
        source = session.get(Source, x.source_id)
        evidence.append(
            {
                "id": x.id,
                "passage": x.passage,
                "locator": x.locator,
                "source_title": source.title,
                "source_url": source.url,
            }
        )
    findings = [
        {
            "subclaim_id": x.subclaim_id,
            "evidence_id": x.evidence_id,
            "assessment": x.assessment,
            "rationale": x.rationale,
        }
        for x in session.scalars(select(Finding).where(Finding.case_id == case_id))
    ]
    return case, subclaims, evidence, findings


def process_job(job_id: str) -> None:
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None or job.status != "running":
            return
        parent = propagate.extract({"traceparent": job.traceparent}) if job.traceparent else None
        kind = job.kind
    with trace.get_tracer("bot_social.worker").start_as_current_span(
        f"job.{kind}", context=parent
    ) as span:
        span.set_attribute("job.id", job_id)
        span.set_attribute("job.kind", kind)
        _process_job(job_id)


def _process_job(job_id: str) -> None:
    # The lease is long enough for a bounded model call. A production provider may
    # require a heartbeat or a longer lease; an expired worker must not commit.
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None or job.status != "running":
            return
        expected_attempts = job.attempts
        case, subclaims, evidence, findings = _snapshot(session, job.case_id)
        try:
            if job.kind == "research":
                source = session.scalar(
                    select(Source)
                    .where(Source.case_id == case.id, Source.content.is_not(None))
                    .limit(1)
                )
                output = agents.research(
                    case.claim, case.source_url, source.content if source else None
                )
            elif job.kind == "review":
                if not evidence:
                    raise ValueError("Review requires evidence")
                output = agents.review(subclaims, evidence)
            elif job.kind == "editorial":
                output = agents.editorial(case.claim, subclaims, evidence, findings)
            else:
                raise ValueError(f"Unknown job kind: {job.kind}")
        except Exception as exc:
            job.error = str(exc)[:2000]
            job.status = "failed" if job.attempts >= MAX_ATTEMPTS else "pending"
            job.lease_until = None
            session.commit()
            return

        # Recheck the lease under row lock before committing any output. This
        # prevents a late worker from duplicating a result after another claims it.
        session.expire_all()
        job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        lease_until = (
            job.lease_until.replace(tzinfo=timezone.utc)
            if job.lease_until and job.lease_until.tzinfo is None
            else job.lease_until
        )
        if (
            job.status != "running"
            or job.attempts != expected_attempts
            or lease_until is None
            or lease_until < now()
        ):
            session.rollback()
            return
        case = session.get(Case, job.case_id)
        if job.kind == "research":
            if not session.scalar(select(Subclaim).where(Subclaim.case_id == case.id).limit(1)):
                for text in output.subclaims:
                    if text.strip():
                        session.add(Subclaim(case_id=case.id, text=text.strip()))
            source = session.scalar(
                select(Source)
                .where(Source.case_id == case.id, Source.content.is_not(None))
                .limit(1)
            )
            if source:
                for passage in output.passages:
                    session.add(
                        Evidence(
                            case_id=case.id,
                            source_id=source.id,
                            passage=passage.quote,
                            locator=passage.locator,
                        )
                    )
            if output.passages:
                case.status = "reviewing"
                enqueue(session, case.id, "review")
            else:
                case.status = "awaiting_evidence"
        elif job.kind == "review":
            for old in session.scalars(select(Finding).where(Finding.case_id == case.id)).all():
                session.delete(old)
            for item in output.findings:
                session.add(
                    Finding(
                        case_id=case.id,
                        subclaim_id=item.subclaim_id,
                        evidence_id=item.evidence_id,
                        assessment=item.assessment,
                        rationale=item.rationale,
                    )
                )
            for question in output.follow_up_questions:
                if question.strip():
                    session.add(
                        Post(case_id=case.id, kind="research_request", text=question.strip())
                    )
            case.status = "reviewing"
            enqueue(session, case.id, "editorial")
        else:
            existing = session.scalar(
                select(Verdict).where(Verdict.case_id == case.id, Verdict.status == "draft")
            )
            if existing is None:
                max_revision = max(
                    (
                        v.revision
                        for v in session.scalars(select(Verdict).where(Verdict.case_id == case.id))
                    ),
                    default=0,
                )
                session.add(
                    Verdict(
                        case_id=case.id,
                        revision=max_revision + 1,
                        text=output.text,
                        evidence_ids=json.dumps(output.evidence_ids),
                    )
                )
            case.status = "draft"
        job.status = "done"
        job.lease_until = None
        job.error = None
        session.commit()


def run_forever(poll_seconds: float = 2) -> None:
    from .telemetry import configure_tracing

    configure_tracing("bot-social-worker")
    while True:
        with SessionLocal() as session:
            job_id = claim_job(session)
        if job_id:
            process_job(job_id)
        else:
            time.sleep(poll_seconds)
