import importlib.util
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock

os.environ["DATABASE_URL"] = "sqlite:////tmp/bot-social-test.db"

import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from bot_social.api import mount_web_assets, ready
from bot_social.db import database_url
from bot_social.deployment import wait_for_schema

RENDER_PATH = Path(__file__).resolve().parents[2] / "deployment" / "render.py"
spec = importlib.util.spec_from_file_location("platform_render", RENDER_PATH)
assert spec and spec.loader
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


def test_managed_postgres_url_escapes_password(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for key, value in {
        "PGHOST": "db.internal",
        "PGPORT": "5432",
        "PGDATABASE": "bot_social",
        "PGUSER": "bot_social",
        "PGPASSWORD": "p@ss/word%",
        "PGSSLMODE": "disable",
    }.items():
        monkeypatch.setenv(key, value)
    assert "p%40ss%2Fword%25" in database_url()
    assert "sslmode=disable" in database_url()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    assert database_url() == "sqlite:///test.db"


def test_web_asset_mount_routes_spa_without_shadowing_api(tmp_path):
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<title>Bot Social</title>")
    (directory / "assets" / "app.js").write_text("console.log('ok')")
    web_app = FastAPI()

    @web_app.get("/api/status")
    def status():
        return {"status": "ok"}

    mount_web_assets(web_app, directory)
    paths = [route.path for route in web_app.routes]
    assert paths.index("/api/status") < paths.index("/assets")
    assert "/" in paths
    assert "/cases/{case_id}" in paths
    assert "/api/{path:path}" not in paths
    page = next(route for route in web_app.routes if route.path == "/")
    assert page.endpoint().path == directory / "index.html"


def test_worker_waits_until_schema_exists(monkeypatch):
    connection = MagicMock()
    failure = OperationalError("SELECT", {}, Exception("relation does not exist"))
    engine = Mock()
    engine.connect.side_effect = [failure, connection]
    sleep = Mock()
    monkeypatch.setattr("bot_social.deployment.engine", engine)
    monkeypatch.setattr("bot_social.deployment.time.sleep", sleep)
    wait_for_schema(0.5)
    assert engine.connect.call_count == 2
    sleep.assert_called_once_with(0.5)


def test_worker_fails_when_schema_never_becomes_ready(monkeypatch):
    engine = Mock()
    engine.connect.side_effect = OperationalError("SELECT", {}, Exception("unavailable"))
    monkeypatch.setattr("bot_social.deployment.engine", engine)
    monkeypatch.setattr("bot_social.deployment.time.monotonic", Mock(side_effect=[0, 2]))
    with pytest.raises(RuntimeError, match="did not become ready"):
        wait_for_schema(timeout_seconds=1)


def test_platform_web_entry_uses_json_logging_without_raw_access_logs(monkeypatch):
    from bot_social import deployment

    configure = Mock()
    upgrade = Mock()
    run = Mock()
    monkeypatch.setattr(deployment, "configure_logging", configure)
    monkeypatch.setattr(deployment.command, "upgrade", upgrade)
    monkeypatch.setattr(deployment.uvicorn, "run", run)
    monkeypatch.setattr(deployment.sys, "argv", ["deployment", "serve"])

    deployment.main()

    configure.assert_called_once_with()
    upgrade.assert_called_once()
    assert upgrade.call_args.args[0].attributes["platform_logging"] is True
    assert run.call_args.kwargs["log_config"] is None
    assert run.call_args.kwargs["access_log"] is False


def test_api_readiness_reports_missing_schema():
    session = Mock()
    session.execute.side_effect = OperationalError("SELECT", {}, Exception("missing table"))
    with pytest.raises(Exception) as error:
        ready(session)
    assert error.value.status_code == 503


def test_platform_declaration_has_separate_bindings_and_rejects_bad_inputs():
    web_id = "11111111-1111-1111-1111-111111111111"
    worker_id = "22222222-2222-2222-2222-222222222222"
    result = render.declaration("bot-social", web_id, worker_id)
    assert result["metadata"] == {"name": "bot-social"}
    web, worker = result["spec"]["components"]
    assert web["bindings"] == [{"bindingId": web_id}]
    assert worker["bindings"] == [{"bindingId": worker_id}]
    assert web["health"]["readiness"]["path"] == "/health/ready"
    assert worker["runtime"]["command"][-1] == "worker"
    assert web["runtime"]["image"] == "eseidinger/bot-social:latest"
    assert worker["runtime"]["image"] == "eseidinger/bot-social:latest"
    with pytest.raises(ValueError):
        render.declaration("Bot Social", web_id, worker_id)
    with pytest.raises(ValueError):
        render.declaration("bot-social", web_id, web_id)


def test_platform_declaration_connects_research_hosts_to_worker_egress():
    result = render.declaration(
        "bot-social",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        model="openai:gpt-6.1-sol",
        outbound_dns=("api.openai.com",),
        research_hosts=("pubmed.ncbi.nlm.nih.gov", "arxiv.org"),
    )
    assert result["spec"]["configuration"]["values"]["BOT_SOCIAL_RESEARCH_HOSTS"] == (
        "pubmed.ncbi.nlm.nih.gov,arxiv.org"
    )
    assert result["spec"]["components"][1]["outbound"] == [
        {"dns": host, "port": 443}
        for host in ("api.openai.com", "pubmed.ncbi.nlm.nih.gov", "arxiv.org")
    ]
    with pytest.raises(ValueError, match="five unique"):
        render.declaration(
            "bot-social",
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
            outbound_dns=("api.openai.com",),
            research_hosts=("a.example", "b.example", "c.example", "d.example", "e.example"),
        )
