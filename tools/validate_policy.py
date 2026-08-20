#!/usr/bin/env python3
"""POLICY-AS-CODE VALIDATION.

This is the gate that makes the standards real. Every rule here corresponds to
a promise the framework makes; if a rule cannot be checked mechanically it does
not belong in the standard.

Checks, in the order the CI pipeline reports them:

  SCHEMA        archetype required fields, vocabularies
  REFERENCE     slo_id / runbook / workflow / domain resolve to registries
  SCOPE         every query is scoped (no org-wide wildcards)
  CARDINALITY   ≤3 group keys, no identity keys, notify_by on wide fanouts
  DETECTION     predictive-first; fixed thresholds carry a written rationale
  PRIORITY      impact_class is legal and paging stays inside policy
  COMPOSITE     identical groupings, explicit ownership, budget
  PACKS         service archetypes reference archetypes that exist
  SLO           every archetype maps to a real SLO; members exist
  SLO_PROFILE   profiles, the resolution chain, and every service's own
                objectives resolve to a measurable SLI (§12)
  EXCEPTION     required fields, expiry, maximum lifetime, approver
  AUTOMATION    workflow classes carry their required safeguards
  BUDGET        the estate stays inside the monitor and paging budgets
"""
from __future__ import annotations

import datetime as dt
import sys

import obs_common as oc
import slo_resolver

REQUIRED_ARCHETYPE_FIELDS = [
    "title", "signal", "impact_class", "detection", "monitor_type",
    "resource_type", "query", "thresholds", "envs", "bands",
    "slo_id", "runbook", "workflow", "failure_domain",
]


def lint() -> list[str]:
    policy = oc.load_policy()
    g = policy["global"]
    vocab = g["tag_vocabulary"]
    card = g["cardinality"]
    errors: list[str] = []

    def err(section: str, where: str, msg: str) -> None:
        errors.append(f"[{section}] {where}: {msg}")

    # ---------------------------------------------------------------- archetypes
    for aid, a in policy["archetypes"].items():
        where = f"archetype {aid}"

        # SCHEMA
        for f in REQUIRED_ARCHETYPE_FIELDS:
            if f not in a:
                err("SCHEMA", where, f"missing required field `{f}`")
        if any(f not in a for f in REQUIRED_ARCHETYPE_FIELDS):
            continue
        if a["impact_class"] not in vocab["impact_class"]:
            err("SCHEMA", where, f"impact_class {a['impact_class']!r} not in vocabulary")
        if a["detection"] not in vocab["detection"]:
            err("SCHEMA", where, f"detection {a['detection']!r} not in vocabulary")
        if a["domain"] not in vocab["domain"]:
            err("SCHEMA", where, f"domain {a['domain']!r} not in vocabulary")
        for e in a["envs"]:
            if e not in vocab["env"]:
                err("SCHEMA", where, f"env {e!r} not in vocabulary")
        for b in a["bands"]:
            if b not in ("baseline", "standard", "critical"):
                err("SCHEMA", where, f"band {b!r} is not an alerting band")
        # dev is an alerting environment now, but a deliberately narrow one:
        # baseline band only, P4 only, Teams only (platform/policy/
        # environments.yaml). An archetype that opts into dev without declaring
        # the baseline band produces nothing at all, which is a silent no-op
        # rather than an error at plan time — so it is caught here.
        if "dev" in a["envs"] and "baseline" not in a["bands"]:
            err("SCHEMA", where,
                "declares env `dev` but not the `baseline` band. dev instantiates "
                "the baseline band only, so this archetype would create no dev "
                "monitor at all")

        # REFERENCE
        if a["slo_id"] not in policy["slos"]:
            err("REFERENCE", where, f"slo_id {a['slo_id']!r} is not in the SLO catalog")
        if a["runbook"] not in policy["runbooks"]:
            err("REFERENCE", where, f"runbook {a['runbook']!r} is not in the runbook registry")
        if a["workflow"] not in policy["workflows"]:
            err("REFERENCE", where, f"workflow {a['workflow']!r} is not in the workflow registry")

        # SCOPE — an unscoped query silently monitors the entire organization.
        if "__SCOPE__" not in a["query"] and "__ESCOPE__" not in a["query"]:
            err("SCOPE", where, "query has no __SCOPE__/__ESCOPE__ placeholder, so it "
                                "would not be limited to an environment or alert band")
        for pattern in card["forbidden_query_patterns"]:
            if pattern in a["query"]:
                err("SCOPE", where, f"query contains the org-wide wildcard {pattern!r}")

        # CARDINALITY
        gb = a.get("group_by", [])
        if len(gb) > card["max_group_by_keys"]:
            err("CARDINALITY", where,
                f"group_by has {len(gb)} keys; maximum is {card['max_group_by_keys']}")
        banned = sorted(set(gb) & set(card["forbidden_group_keys"]))
        if banned:
            err("CARDINALITY", where, f"group_by uses banned identity keys {banned}")
        # The group_by must actually appear in the query, or the monitor is not
        # grouped the way the catalog claims and the matrix will lie.
        for key in gb:
            if key not in a["query"]:
                err("CARDINALITY", where,
                    f"group_by declares {key!r} but the query does not group by it")

        # AUTO-RESOLVE — an archetype may choose its own window, but only
        # inside the policy range. Anything outside it is rejected by the
        # monitor factory's precondition at plan time; catching it here means
        # the author sees why in the pull request instead of in a failed apply.
        ar = g["monitor_defaults"]["auto_resolve"]
        if "auto_resolve_hours" in a:
            h = a["auto_resolve_hours"]
            if not isinstance(h, int) or isinstance(h, bool) or \
                    not (ar["min_hours"] <= h <= ar["max_hours"]):
                err("SCHEMA", where,
                    f"auto_resolve_hours {h!r} must be a whole number of hours between "
                    f"{ar['min_hours']} and {ar['max_hours']}. 0 means the monitor never "
                    "resolves itself, which suppresses its own next alert")

        # DETECTION — predictive-first
        behavioral = a["signal"] in g["detection_policy"]["behavioral_signals"]
        absolute_ok = a["signal"] in g["detection_policy"]["absolute_threshold_allowed_signals"]
        if a["detection"] == "threshold":
            if behavioral and not absolute_ok and not a.get("rationale_fixed_threshold"):
                err("DETECTION", where,
                    f"fixed threshold on the behavioral signal {a['signal']!r} without "
                    "`rationale_fixed_threshold`. Use anomaly/forecast/outlier detection, "
                    "or write down why the number itself has operational meaning")
            if not a.get("rationale_fixed_threshold"):
                err("DETECTION", where,
                    "every fixed-threshold archetype must record "
                    "`rationale_fixed_threshold` — the number has to mean something")
        elif a["detection"] in ("anomaly", "seasonal_anomaly", "forecast", "outlier", "rate_of_change"):
            if not any(fn in a["query"] for fn in oc.PREDICTIVE_FUNCS):
                err("DETECTION", where,
                    f"detection={a['detection']} but the query uses no predictive function "
                    f"({', '.join(oc.PREDICTIVE_FUNCS)})")
        if a["detection"] == "seasonal_anomaly" and "seasonality=" not in a["query"]:
            err("DETECTION", where, "seasonal_anomaly must declare seasonality= in the query")

        # PRIORITY — verify the resolved priority is sane for every instance
        for env in a["envs"]:
            for band in a["bands"]:
                if band not in policy["environments"][env]["bands_instantiated"]:
                    continue
                p = oc.resolve_priority(policy, a["impact_class"], band, env)
                if oc.pages(policy, p, band, env) and env != "prod":
                    err("PRIORITY", where, f"resolves to a paging monitor in {env}")

    # ---------------------------------------------------------------- composites
    budget = policy["composites_doc"]["budget"]
    if len(policy["composites"]) > budget["max_composites"]:
        err("COMPOSITE", "budget",
            f"{len(policy['composites'])} composites exceeds the budget of {budget['max_composites']}")
    for cid, c in policy["composites"].items():
        where = f"composite {cid}"
        if len(c["members"]) > budget["max_members_per_composite"]:
            err("COMPOSITE", where, f"more than {budget['max_members_per_composite']} members")
        member_groupings = set()
        member_teams = set()
        for m in c["members"]:
            if m not in policy["archetypes"]:
                err("REFERENCE", where, f"member {m!r} is not an archetype")
                continue
            ma = policy["archetypes"][m]
            member_groupings.add(tuple(ma.get("group_by", [])))
            member_teams.add(policy["domains"][ma["domain"]].get(
                "routing_override_team", policy["domains"][ma["domain"]]["owner_team"]))
            for band in c["bands"]:
                if band not in ma["bands"]:
                    err("COMPOSITE", where,
                        f"member {m!r} is not instantiated in band {band!r}")
            for env in c["envs"]:
                if env not in ma["envs"]:
                    err("COMPOSITE", where,
                        f"member {m!r} is not instantiated in env {env!r}")
        if len(member_groupings) > 1:
            err("COMPOSITE", where,
                f"members have different group_by sets {sorted(member_groupings)}. Datadog "
                "only evaluates a composite per group when the groupings match; otherwise it "
                "correlates unrelated resources")
        if not c.get("owner_team"):
            err("COMPOSITE", where, "missing owner_team — a composite must have one owner")
        elif c["owner_team"] not in policy["teams"]:
            err("REFERENCE", where, f"owner_team {c['owner_team']!r} is not a registered team")
        unnamed = member_teams - {c.get("owner_team")} - set(c.get("cc_teams", []))
        if unnamed:
            err("COMPOSITE", where,
                f"members belong to {sorted(unnamed)} which are neither owner_team nor cc_teams")

    # --------------------------------------------------------------------- packs
    for said, sa in policy["service_archetypes"].items():
        for pack in sa["packs"]:
            if pack not in policy["packs"]:
                err("PACKS", f"service_archetype {said}", f"unknown pack {pack!r}")
    for pid, pack in policy["packs"].items():
        for aid in pack["archetypes"]:
            if aid not in policy["archetypes"]:
                err("PACKS", f"pack {pid}", f"references unknown archetype {aid!r}")

    # ----------------------------------------------------------------------- SLO
    for sid, s in policy["slos"].items():
        where = f"slo {sid}"
        if s["team"] not in policy["teams"]:
            err("REFERENCE", where, f"team {s['team']!r} is not registered")
        if s["domain"] not in policy["domains"]:
            err("REFERENCE", where, f"domain {s['domain']!r} is unknown")
        for m in s.get("member_archetypes", []):
            if m not in policy["archetypes"]:
                err("REFERENCE", where, f"member_archetype {m!r} does not exist")
        for w in s.get("burn_alerts", []):
            if w not in policy["global"]["burn_rate_windows"]:
                err("REFERENCE", where, f"burn window {w!r} is not defined in global.yaml")
        if s["type"] == "metric" and "query" not in s:
            err("SCHEMA", where, "metric SLOs require a query")
        if s["type"] == "monitor" and not s.get("member_archetypes"):
            err("SCHEMA", where, "monitor SLOs require member_archetypes")

    # ------------------------------------------------- SLO profiles (§12, §15)
    # The profile catalog, the resolution chain and every service's own `slo:`
    # block. Implemented in tools/slo_resolver.py, which is the same resolver
    # the coverage report and the tests use — a rule that only the linter knows
    # is a rule the platform does not actually follow.
    errors.extend(slo_resolver.validate(policy))

    relations = policy["slo_profiles_doc"]["slo_relations"]
    slo_members = {
        m for s in policy["slos"].values() if s["type"] == "monitor"
        for m in s.get("member_archetypes", [])
    }
    for aid, a in policy["archetypes"].items():
        where = f"archetype {aid}"
        rel = a.get("slo_relation")
        if not rel:
            err("SCHEMA", where, "missing `slo_relation` — every monitor must state HOW it "
                                 "relates to an objective, not just which one (§15)")
            continue
        if rel not in relations:
            err("SCHEMA", where, f"slo_relation {rel!r} is not in the vocabulary "
                                 f"({', '.join(sorted(relations))})")
            continue
        # `sli_producing` is the only relation with a mechanical definition:
        # the monitor IS a member of a monitor-based SLO, so its state consumes
        # that budget directly. Both directions are checked, because the
        # dangerous drift is the quiet one — an archetype dropped from an SLO's
        # membership while still claiming to produce its SLI.
        if rel == "sli_producing" and aid not in slo_members:
            err("REFERENCE", where, "declares slo_relation `sli_producing` but is not a member "
                                    "of any monitor-based SLO, so it produces no SLI")
        if rel != "sli_producing" and aid in slo_members:
            err("REFERENCE", where, f"is a member of a monitor-based SLO (its state consumes an "
                                    f"error budget) but declares slo_relation {rel!r}")
        # A security detection is one either by domain or by signal: a WAF block
        # surge on the cloud platform and a failed-login anomaly on a database
        # are security findings that happen to live in another team's catalog
        # file, and classifying them as diagnostics would hide them from the
        # security operating model.
        if rel == "security" and a["domain"] != "security" and a["signal"] != "auth_anomaly":
            err("SCHEMA", where, "slo_relation `security` is for the security domain or an "
                                 "auth_anomaly signal; a security-adjacent monitor elsewhere is "
                                 "still supporting or diagnostic")
        if rel == "compliance" and not a.get("compliance"):
            err("SCHEMA", where, "slo_relation `compliance` without `compliance: true` — the "
                                 "classification claims audit evidence the monitor is not tagged "
                                 "as producing")

    # ---------------------------------------------------------------- exceptions
    today = dt.date.today()
    exc_policy = policy["exceptions_doc"]["policy"]
    seen_ids = set()
    for e in policy["exceptions"]:
        eid = e.get("id", "<missing id>")
        where = f"exception {eid}"
        for f in ("id", "scope", "control", "value", "reason", "owner", "approved_by",
                  "approved_on", "expires"):
            if f not in e:
                err("EXCEPTION", where, f"missing required field `{f}`")
        if eid in seen_ids:
            err("EXCEPTION", where, "duplicate exception id")
        seen_ids.add(eid)
        if "expires" not in e or "approved_on" not in e:
            continue
        expires = e["expires"] if isinstance(e["expires"], dt.date) else dt.date.fromisoformat(str(e["expires"]))
        approved = e["approved_on"] if isinstance(e["approved_on"], dt.date) else dt.date.fromisoformat(str(e["approved_on"]))
        if expires < today:
            err("EXCEPTION", where, f"EXPIRED on {expires} — renew with a new justification or remove")
        if e.get("control") == "threshold":
            err("EXCEPTION", where,
                "`threshold` is not an exception control. Datadog requires a monitor's "
                "thresholds to match the number inside its query, so a threshold change "
                "is a catalog change (or a custom self-service monitor), never metadata")
        max_days = exc_policy["max_duration_days"].get(e.get("control"))
        if max_days and (expires - approved).days > max_days:
            err("EXCEPTION", where,
                f"lifetime {(expires - approved).days}d exceeds the {max_days}d maximum for "
                f"control {e['control']!r}")
        if e.get("owner") not in policy["teams"]:
            err("REFERENCE", where, f"owner {e.get('owner')!r} is not a registered team")
        required_approver = exc_policy["required_approver"].get(e.get("control"))
        if required_approver and e.get("approved_by") != required_approver:
            err("EXCEPTION", where,
                f"control {e['control']!r} requires approval by {required_approver!r}, "
                f"got {e.get('approved_by')!r}")

    # ---------------------------------------------------------------- automation
    wf_policy = policy["workflows_doc"]["policy"]
    for wid, w in policy["workflows"].items():
        where = f"workflow {wid}"
        if w["team"] not in policy["teams"]:
            err("REFERENCE", where, f"team {w['team']!r} is not registered")
        if w["class"] == "fully_automatic":
            for f in wf_policy["fully_automatic_requires"]:
                if f not in w:
                    err("AUTOMATION", where, f"fully_automatic requires `{f}`")
            if not w.get("reversible", False):
                err("AUTOMATION", where, "fully_automatic must be reversible")
        if w["class"] == "approval_required":
            for f in wf_policy["approval_required_requires"]:
                if f not in w:
                    err("AUTOMATION", where, f"approval_required requires `{f}`")
        if not w.get("reversible", True) and w.get("approval") != "change-board":
            err("AUTOMATION", where,
                "irreversible automation requires change-board approval, not owner approval")
        if w["class"] == "diagnostic_only" and not w.get("read_only"):
            err("AUTOMATION", where, "diagnostic_only workflows must be read_only")

    # -------------------------------------------------------------------- teams
    for tid, t in policy["teams"].items():
        for f in ("name", "email", "teams_channel", "teams_low_noise_channel",
                  "servicenow_assignment_group", "escalation_to"):
            if f not in t:
                err("SCHEMA", f"team {tid}", f"missing `{f}`")

    # ------------------------------------------------------------------- budget
    instances = oc.expand_instances(policy)
    paging = [i for i in instances if i["pages"]]
    p1 = [i for i in instances if i["priority"] == "P1"]
    if len(instances) > card["max_total_managed_monitors"]:
        err("BUDGET", "estate",
            f"{len(instances)} archetype instances exceeds the "
            f"{card['max_total_managed_monitors']} monitor budget")
    if len(paging) > card["max_paging_monitors"]:
        err("BUDGET", "paging",
            f"{len(paging)} paging patterns exceeds the {card['max_paging_monitors']} budget")
    if len(p1) > card["max_p1_monitors"]:
        err("BUDGET", "P1", f"{len(p1)} P1 patterns exceeds the {card['max_p1_monitors']} budget")
    per_archetype: dict[str, int] = {}
    for i in instances:
        per_archetype[i["archetype"]] = per_archetype.get(i["archetype"], 0) + 1
    for aid, n in per_archetype.items():
        if n > card["max_instances_per_archetype"]:
            err("BUDGET", f"archetype {aid}",
                f"{n} instances exceeds max_instances_per_archetype "
                f"({card['max_instances_per_archetype']})")

    # -------------------------------------------------- storm control (grouping)
    notify_by_policy = policy["grouping"]["notify_by_policy"]
    wide_domains = set(notify_by_policy["standard_collapse_keys"])
    for aid, a in policy["archetypes"].items():
        gb = a.get("group_by", [])
        nb = a.get("notify_by", [])
        if a["domain"] in wide_domains and len(gb) >= 2 and not nb:
            err("CARDINALITY", f"archetype {aid}",
                f"a {a['domain']} archetype grouped by {gb} can fan out across a whole fleet. "
                f"Set notify_by to the broadest of its own group keys (e.g. [{gb[0]}]) so a "
                "platform-wide event sends one notification per collapse key instead of "
                "thousands")
        if nb and not set(nb).issubset(set(gb)):
            err("CARDINALITY", f"archetype {aid}",
                f"notify_by {nb} is not a subset of group_by {gb}. A collapse key that is not "
                "a group key does nothing at all, which looks like storm control while "
                "providing none")

    return errors


def main() -> int:
    errors = lint()
    for e in errors:
        print(f"POLICY VIOLATION: {e}")
    print(f"\npolicy lint: {'FAIL' if errors else 'OK'} ({len(errors)} violations)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
