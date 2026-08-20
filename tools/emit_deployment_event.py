#!/usr/bin/env python3
"""DEPLOYMENT MARKER — this repository's own version, emitted to Datadog (§8).

`docs/tagging-standard.md` § Deployment metadata states the contract every
application pipeline must implement: DD_VERSION, DD_GIT_COMMIT_SHA and
DD_GIT_REPOSITORY_URL on the telemetry, so that deployment → error → latency →
SLO → incident correlation is real rather than assumed.

This repository cannot implement that contract on somebody else's behalf. What
it CAN do is implement it for the one service it actually deploys: the
monitoring configuration itself. A change to alerting that correlates with a
change in alert behaviour is a real thing to be able to see, and until now
there was no marker in Datadog saying when this platform changed.

That is the whole scope. Writing something that claimed to set DD_VERSION for
the estate's applications would be inventing a capability — those variables
live in those teams' pipelines, and no amount of code here reaches them.

The event carries UNIFIED SERVICE TAGS (`service`, `env`, `version`) because
those are the keys every correlation in Datadog joins on. An event tagged
anything else is a note nobody can find.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import obs_common as oc

# Deliberately the v1 Events API rather than the DORA deployment endpoint. DORA
# is the better home for this and should be adopted when the org has it
# enabled; events are available to EVERY org today, and a marker that exists is
# worth more than a better-shaped one that 403s in half the environments.
EVENTS_PATH = "/api/v1/events"


def build_payload(env_vars: dict) -> dict:
    """The event, from environment alone — no I/O, so the tests can assert it.

    Every required variable is read strictly: a marker missing its version is
    the exact defect this file exists to fix, so producing one silently would
    be self-defeating.
    """
    missing = [k for k in ("DD_SERVICE", "DD_ENV", "DD_VERSION",
                           "DD_GIT_COMMIT_SHA", "DD_GIT_REPOSITORY_URL")
               if not env_vars.get(k)]
    if missing:
        raise SystemExit(
            "deployment marker not emitted — missing " + ", ".join(missing) +
            ". These are set by .github/workflows/deploy.yml; see "
            "docs/tagging-standard.md § Deployment metadata."
        )

    service = env_vars["DD_SERVICE"]
    env = env_vars["DD_ENV"]
    version = env_vars["DD_VERSION"]
    sha = env_vars["DD_GIT_COMMIT_SHA"]
    repo = env_vars["DD_GIT_REPOSITORY_URL"]

    return {
        "title": f"Deployed {service} {version} to {env}",
        "text": (
            f"%%%\n"
            f"Monitoring configuration applied by the deploy pipeline.\n\n"
            f"- version: `{version}`\n"
            f"- commit: `{sha}`\n"
            f"- repository: {repo}\n"
            f"%%%"
        ),
        "alert_type": "info",
        "source_type_name": "my_apps",
        # `deployment` is what the event overlay and the deployment-correlation
        # views filter on; without it this is an untyped note.
        "tags": sorted([
            f"service:{service}",
            f"env:{env}",
            f"version:{version}",
            f"git.commit.sha:{sha}",
            f"git.repository_url:{repo}",
            "event_type:deployment",
            # NOT `managed_by:terraform` — this event is posted by the
            # pipeline, not created by Terraform, and the drift detector reads
            # that tag to decide what it owns.
            "source:observability-platform-deploy",
        ]),
        # Aggregating on the service keeps one deployment stream per service
        # instead of a flat list nobody can read.
        "aggregation_key": f"deployment:{service}:{env}",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print the payload and exit — used by the tests and "
                         "safe to run without credentials")
    args = ap.parse_args()

    payload = build_payload(dict(os.environ))
    if args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    r = oc.dd_request("POST", oc.dd_site() + EVENTS_PATH,
                      headers=oc.dd_headers(), data=json.dumps(payload))
    if r.status_code >= 300:
        print(f"deployment marker FAILED ({r.status_code}): {r.text[:400]}")
        return 1
    print(f"deployment marker emitted: {payload['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
