#!/usr/bin/env python3
"""Render the Developer Platform v1 declaration for Bot Social."""

import argparse
import json
import re
from pathlib import Path
from uuid import UUID

SLUG = re.compile(r"^[a-z](?:[a-z0-9-]{0,30}[a-z0-9])?$")
IMAGE = "eseidinger/bot-social:latest"
HOST = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)


def declaration(
    project: str,
    web_binding: str,
    worker_binding: str,
    *,
    moderator_group: str = "moderator",
    model: str | None = None,
    outbound_dns: tuple[str, ...] = (),
    research_hosts: tuple[str, ...] = (),
) -> dict:
    if not SLUG.fullmatch(project):
        raise ValueError("project must be a lowercase platform slug of at most 32 characters")
    if not SLUG.fullmatch(moderator_group):
        raise ValueError("moderator group must be a platform group-name slug")
    destinations = outbound_dns + research_hosts
    if (
        len(destinations) > 5
        or len(set(destinations)) != len(destinations)
        or any(not HOST.fullmatch(host) for host in destinations)
    ):
        raise ValueError("supply at most five unique lowercase DNS hostnames")
    web_id = str(UUID(web_binding))
    worker_id = str(UUID(worker_binding))
    if web_id == worker_id:
        raise ValueError("web and worker need separate component bindings")

    def runtime(mode: str) -> dict:
        return {
            "type": "container",
            "image": IMAGE,
            "command": ["python", "-m", "bot_social.deployment", mode],
        }

    return {
        "apiVersion": "platform.eseidinger.de/v1",
        "kind": "Application",
        "metadata": {"name": project},
        "spec": {
            "components": [
                {
                    "name": "web",
                    "type": "service",
                    "runtime": runtime("serve"),
                    "ports": [{"name": "http", "protocol": "http", "port": 8080}],
                    "exposure": "public",
                    "replicas": 1,
                    "bindings": [{"bindingId": web_id}],
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "256Mi"},
                        "limits": {"cpu": "500m", "memory": "512Mi"},
                    },
                    "health": {"readiness": {"path": "/health/ready"}},
                    "telemetry": {"tracing": {"enabled": True}},
                },
                {
                    "name": "worker",
                    "type": "service",
                    "runtime": runtime("worker"),
                    "bindings": [{"bindingId": worker_id}],
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "256Mi"},
                        "limits": {"cpu": "1", "memory": "1Gi"},
                    },
                    "telemetry": {"tracing": {"enabled": True}},
                    "outbound": [{"dns": host, "port": 443} for host in destinations],
                },
            ],
            "configuration": {
                "values": {
                    "MODERATOR_GROUP_NAME": moderator_group,
                    **({"BOT_SOCIAL_MODEL": model} if model else {}),
                    **(
                        {"BOT_SOCIAL_RESEARCH_HOSTS": ",".join(research_hosts)}
                        if research_hosts
                        else {}
                    ),
                }
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="bot-social")
    parser.add_argument("--web-binding", required=True)
    parser.add_argument("--worker-binding", required=True)
    parser.add_argument("--moderator-group", default="moderator")
    parser.add_argument("--model", help="non-secret Pydantic AI model name")
    parser.add_argument("--outbound-dns", action="append", default=[])
    parser.add_argument("--research-hosts-file", type=Path, help="JSON array of research hosts")
    args = parser.parse_args()
    try:
        research_hosts = ()
        if args.research_hosts_file:
            hosts = json.loads(args.research_hosts_file.read_text())
            if not isinstance(hosts, list) or not hosts or not all(
                isinstance(host, str) for host in hosts
            ):
                raise ValueError("research-hosts-file must contain a nonempty JSON string array")
            research_hosts = tuple(hosts)
        spec = declaration(
            args.project,
            args.web_binding,
            args.worker_binding,
            moderator_group=args.moderator_group,
            model=args.model,
            outbound_dns=tuple(args.outbound_dns),
            research_hosts=research_hosts,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(spec, indent=2))


if __name__ == "__main__":
    main()
