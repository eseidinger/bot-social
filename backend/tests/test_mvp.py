import asyncio
import os
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path('/tmp/bot-social-test.db')}"
os.environ["MODERATOR_GROUP_NAME"] = "moderator"
os.environ.pop("BOT_SOCIAL_MODEL", None)

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from bot_social import agents
from bot_social.api import app, moderator, publish_verdict, retry_research, start_review
from bot_social.db import Base, SessionLocal, engine
from bot_social.models import Case, Evidence, Job, Source, Subclaim, Verdict, now
from bot_social.web_research import FetchedPage
from bot_social.workflow import _lock_current_attempt, claim_job, enqueue, process_job


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def run_next_job():
    with SessionLocal() as session:
        job_id = claim_job(session)
    assert job_id
    process_job(job_id)
    return job_id


def test_api_does_not_advertise_cross_origin_access():
    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.options(
                "/api/cases",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers


def test_roles_use_exact_group_name_and_protect_moderation(monkeypatch):
    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (await client.get("/api/roles")).json() == []
            assert (
                await client.get(
                    "/api/roles",
                    headers={"X-Platform-Principal-Group-Ids": "moderator"},
                )
            ).json() == []
            assert (
                await client.get(
                    "/api/roles",
                    headers={"X-Platform-Principal-Group-Names": "moderator-other"},
                )
            ).json() == []
            assert (
                await client.get(
                    "/api/roles",
                    headers={"X-Platform-Principal-Group-Names": "reader moderator"},
                )
            ).json() == ["moderator"]
            monkeypatch.delenv("MODERATOR_GROUP_NAME")
            assert (
                await client.get(
                    "/api/roles",
                    headers={"X-Platform-Principal-Group-Names": "moderator"},
                )
            ).json() == []

    asyncio.run(request())
    with pytest.raises(HTTPException) as denied:
        moderator([])
    assert denied.value.status_code == 403
    assert moderator(["moderator"]) is None


def test_research_job_persists_a_fetched_source_and_verified_quote(monkeypatch):
    page = FetchedPage("https://example.org/report", "Motor report", ("The motor stopped.",))
    result = agents.ResearchResult(
        subclaims=["The motor runs without external power."],
        passages=[
            agents.ResearchPassage(
                source_url=page.url, quote="The motor stopped.", locator="paragraph 1"
            )
        ],
    )
    monkeypatch.setattr(
        agents,
        "research",
        lambda *args: agents.ResearchOutcome(result=result, pages={page.url: page}, notes=()),
    )
    with SessionLocal() as session:
        case = Case(claim="The motor runs without external power.", source_url=page.url)
        session.add(case)
        session.flush()
        enqueue(session, case.id, "research")
        session.commit()
        case_id = case.id

    run_next_job()
    with SessionLocal() as session:
        source = session.query(Source).filter_by(case_id=case_id).one()
        evidence = session.query(Evidence).filter_by(case_id=case_id).one()
        assert source.url == page.url
        assert source.content == page.text
        assert evidence.source_id == source.id
        assert evidence.passage == "The motor stopped."
        assert session.get(Case, case_id).status == "reviewing"


def test_moderator_can_retry_a_failed_research_job():
    with SessionLocal() as session:
        case = Case(claim="The motor runs without external power.")
        session.add(case)
        session.flush()
        job = Job(
            case_id=case.id, kind="research", status="failed", attempts=3, error="Web search failed"
        )
        session.add(job)
        session.commit()
        case_id = case.id

    with SessionLocal() as session:
        result = retry_research(case_id, session, None)
        assert result.status == "submitted"
        assert result.jobs[0].status == "pending"
        assert result.jobs[0].attempts == 0
        assert result.jobs[0].error is None
        with pytest.raises(HTTPException) as denied:
            retry_research(case_id, session, None)
        assert denied.value.status_code == 409


def test_stale_worker_attempt_cannot_change_a_reclaimed_job():
    with SessionLocal() as session:
        case = Case(claim="The motor runs without external power.")
        session.add(case)
        session.flush()
        job = enqueue(session, case.id, "research")
        session.commit()
        job_id = job.id

    with SessionLocal() as session:
        assert claim_job(session) == job_id
        job = session.get(Job, job_id)
        assert _lock_current_attempt(session, job_id, expected_attempts=1) is not None
        session.rollback()

    with SessionLocal() as session:
        job = session.get(Job, job_id)
        job.attempts = 2
        job.lease_until = now()
        session.commit()

    with SessionLocal() as session:
        assert _lock_current_attempt(session, job_id, expected_attempts=1) is None
        session.rollback()


def test_rerun_preserves_draft_until_replacement_succeeds(monkeypatch):
    with SessionLocal() as session:
        case = Case(claim="The motor runs without external power.", status="draft")
        session.add(case)
        session.flush()
        session.add(Subclaim(case_id=case.id, text=case.claim))
        source = Source(case_id=case.id, title="Test report")
        session.add(source)
        session.flush()
        evidence = Evidence(
            case_id=case.id, source_id=source.id, passage="The motor stopped.", locator="page 1"
        )
        session.add(evidence)
        session.add(
            Verdict(case_id=case.id, revision=1, text="Previous moderator draft", evidence_ids="[]")
        )
        session.commit()
        case_id = case.id

    with SessionLocal() as session:
        result = start_review(case_id, session, None)
        assert result.verdicts[0].text == "Previous moderator draft"
        verdict_id = result.verdicts[0].id
        with pytest.raises(HTTPException) as blocked:
            publish_verdict(case_id, verdict_id, session, None)
        assert blocked.value.status_code == 409

    monkeypatch.setattr(
        agents, "review", lambda *args: (_ for _ in ()).throw(ValueError("review failed"))
    )
    run_next_job()
    with SessionLocal() as session:
        assert session.get(Verdict, verdict_id).text == "Previous moderator draft"
        assert session.get(Verdict, verdict_id).status == "draft"

    monkeypatch.setattr(agents, "review", lambda *args: agents.ReviewResult(findings=[]))
    run_next_job()
    monkeypatch.setattr(
        agents,
        "editorial",
        lambda *args: agents.EditorialResult(
            text="Updated evidence-based draft", evidence_ids=[evidence.id]
        ),
    )
    run_next_job()
    with SessionLocal() as session:
        drafts = session.query(Verdict).filter_by(case_id=case_id, status="draft").all()
        assert len(drafts) == 1
        assert drafts[0].id != verdict_id
        assert drafts[0].text == "Updated evidence-based draft"
        assert drafts[0].revision == 1


def test_submission_to_publication_and_correction():
    client = TestClient(app)
    headers = {"X-Platform-Principal-Group-Names": "moderator"}
    response = client.post(
        "/api/cases", json={"claim": "The motor generates energy without an external input."}
    )
    assert response.status_code == 201
    case_id = response.json()["id"]

    assert (
        client.post(
            f"/api/cases/{case_id}/evidence", headers={"Authorization": "Bearer wrong"}, json={}
        ).status_code
        == 403
    )
    first_job = run_next_job()
    process_job(first_job)  # idempotent replay
    case = client.get(f"/api/cases/{case_id}").json()
    assert len(case["subclaims"]) == 1
    assert case["status"] == "awaiting_evidence"

    source = client.post(
        f"/api/cases/{case_id}/evidence",
        headers=headers,
        json={
            "title": "Motor test report",
            "url": "https://example.org/report",
            "passage": "The device stopped after its battery was removed.",
            "locator": "page 2",
        },
    )
    assert source.status_code == 201
    evidence_id = source.json()["evidence"][0]["id"]
    source_id = source.json()["sources"][0]["id"]
    assert client.post(f"/api/cases/{case_id}/review", headers=headers).status_code == 200
    run_next_job()
    run_next_job()
    case = client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "draft"
    assert case["findings"][0]["assessment"] == "unclear"
    draft = case["verdicts"][0]
    assert (
        client.post(
            f"/api/cases/{case_id}/verdicts/{draft['id']}/publish", headers=headers
        ).status_code
        == 409
    )
    edited = client.put(
        f"/api/cases/{case_id}/verdicts/{draft['id']}",
        headers=headers,
        json={
            "text": "The supplied test report says the motor stopped when the battery was removed. This undermines the claim of operation without input, but independent replication is still needed.",
            "evidence_ids": [evidence_id],
        },
    )
    assert edited.status_code == 200
    assert (
        client.post(
            f"/api/cases/{case_id}/verdicts/{draft['id']}/publish", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/cases/{case_id}/verdicts/{draft['id']}",
            headers=headers,
            json={"text": "rewrite", "evidence_ids": [evidence_id]},
        ).status_code
        == 409
    )

    corrected = client.post(
        f"/api/sources/{source_id}/corrections",
        headers=headers,
        json={"text": "The test report was updated."},
    )
    assert corrected.status_code == 200
    assert corrected.json()[0]["status"] == "needs_review"

    assert (
        client.post(
            f"/api/cases/{case_id}/objections", json={"text": "A second test is needed."}
        ).status_code
        == 201
    )
    assert client.post(f"/api/cases/{case_id}/review", headers=headers).status_code == 200
    run_next_job()
    run_next_job()
    case = client.get(f"/api/cases/{case_id}").json()
    assert [(v["revision"], v["status"]) for v in case["verdicts"]] == [
        (1, "published"),
        (2, "draft"),
    ]
    assert any(p["kind"] == "objection" for p in case["posts"])
    assert any(p["kind"] == "source_correction" for p in case["posts"])


def test_invalid_evidence_reference_and_review_gate():
    client = TestClient(app)
    headers = {"X-Platform-Principal-Group-Names": "moderator"}
    case_id = client.post(
        "/api/cases", json={"claim": "The moon is made entirely of cheese."}
    ).json()["id"]
    assert client.post(f"/api/cases/{case_id}/review", headers=headers).status_code == 409
    run_next_job()
    response = client.post(
        f"/api/cases/{case_id}/evidence",
        headers=headers,
        json={
            "title": "Secondary account",
            "passage": "This repeats an earlier source.",
            "locator": "paragraph 1",
            "original_source_id": "other-case",
        },
    )
    assert response.status_code == 422
    assert client.get("/api/cases", params={"q": "cheese"}).json()[0]["id"] == case_id


def test_prepared_source_runs_all_three_jobs():
    client = TestClient(app)
    response = client.post(
        "/api/cases",
        json={
            "claim": "The test motor needs no power source to keep running.",
            "source_title": "Prepared test report",
            "source_text": "The motor stopped when the external supply was disconnected.",
        },
    )
    assert response.status_code == 201
    case_id = response.json()["id"]
    for _ in range(3):
        run_next_job()
    case = client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "draft"
    assert [j["kind"] for j in case["jobs"]] == ["research", "review", "editorial"]
    assert (
        case["evidence"][0]["passage"]
        == "The motor stopped when the external supply was disconnected."
    )
    assert case["verdicts"][0]["status"] == "draft"
