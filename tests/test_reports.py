"""The report catalog (§34), the survey (§35), and the dashboard budget (§33).

Two properties are being protected here, and they are the ones that decay
quietly:

  1. The catalog and the implementation cannot drift apart. A catalogued report
     with no code is a promise nobody keeps; code with no catalog entry has no
     audience, no cadence and nobody who reads it.
  2. Every report runs OFFLINE, against the committed fixtures, with no
     credentials. A report family that only works at 6am on a Tuesday against
     the live org is a family nobody can review in a pull request.
"""
import json
from pathlib import Path

import build_inventory
import obs_common as oc
import profile_engine
import reports as rp

FIXTURES = Path(__file__).parent / "fixtures"
POLICY = oc.load_policy()
MONITORS = json.loads((FIXTURES / "monitors_planned.json").read_text())
SLOS = json.loads((FIXTURES / "slos.json").read_text())

FAMILIES = {"executive", "operations", "platform", "database", "azure"}

# The operations reports §34 was actually missing. Named explicitly rather than
# counted, because "seven operations reports" would stay true if somebody
# replaced `flapping` with a second copy of `noisy`.
REQUIRED_OPERATIONS_REPORTS = {
    "ops-silent-monitors",            # monitors that never trigger
    "ops-noisy-monitors",             # monitors that trigger constantly
    "ops-flapping-monitors",          # monitors that oscillate
    "ops-services-without-telemetry",
    "ops-missing-ownership",
    "ops-runbook-coverage",
    "ops-oncall-coverage",
}


def _ctx(live=False, runtime=None, monitors=None):
    resources = build_inventory.synthesize(600)
    inv = {"resources": resources, "resource_count": len(resources)}
    assignments = profile_engine.assign(inv, POLICY, oc.load_services())
    return rp.Context(POLICY, monitors if monitors is not None else MONITORS,
                      SLOS, inv, assignments, live=live, runtime=runtime)


# --- catalog integrity -------------------------------------------------------

def test_catalog_and_implementation_agree_in_both_directions():
    catalogued = set(POLICY["reports"])
    implemented = set(rp.REPORTS)
    assert catalogued == implemented, (
        f"catalogued but not implemented: {sorted(catalogued - implemented)}; "
        f"implemented but not catalogued: {sorted(implemented - catalogued)}")


def test_all_five_families_exist_and_are_populated():
    assert set(POLICY["reports_doc"]["families"]) == FAMILIES
    produced = {r["family"] for r in POLICY["reports"].values()}
    assert produced == FAMILIES, f"family with no reports: {FAMILIES - produced}"


def test_the_missing_operations_reports_exist():
    ops = {r for r, s in POLICY["reports"].items() if s["family"] == "operations"}
    assert REQUIRED_OPERATIONS_REPORTS <= ops, REQUIRED_OPERATIONS_REPORTS - ops


def test_every_report_names_an_audience_a_question_and_an_action():
    """A report with no stated action is a dashboard with extra steps."""
    for rid, spec in POLICY["reports"].items():
        assert spec["audience"], rid
        assert spec["question"].strip().endswith("?"), (
            f"{rid}: the question field must be an actual question")
        assert len(spec["action"].split()) >= 5, f"{rid}: action is not actionable"


def test_every_declared_data_source_is_declared_once():
    declared = set(POLICY["reports_doc"]["data_sources"])
    used = {ds for s in POLICY["reports"].values() for ds in s["data_source"]}
    assert used <= declared, f"undeclared sources: {sorted(used - declared)}"
    assert declared - used == set(), (
        f"declared but unused data sources: {sorted(declared - used)}")


# --- it runs offline ---------------------------------------------------------

def test_every_report_produces_a_summary_offline_with_no_credentials():
    result = rp.run(_ctx())
    assert len(result["reports"]) == len(POLICY["reports"])
    for r in result["reports"]:
        assert "needing_attention" in r["summary"], r["id"]
        assert isinstance(r["summary"]["needing_attention"], int), r["id"]


def test_a_live_only_report_says_it_degraded_rather_than_going_quiet():
    """The honesty property: a weaker claim must be labelled as a weaker claim."""
    result = rp.run(_ctx(), ids=["ops-silent-monitors"])
    r = result["reports"][0]
    assert r["degraded"] is True
    assert r["evidence"] == "structural"
    # ...and it still answers the structural half rather than returning nothing.
    assert r["summary"]["structural_evidence"] >= 0
    assert "rows" in r


def test_markdown_renders_every_family():
    md = rp.to_markdown(rp.run(_ctx()), POLICY)
    for fam in FAMILIES:
        assert POLICY["reports_doc"]["families"][fam]["display"] in md


# --- the reports say something true ------------------------------------------

def test_silent_monitors_finds_a_band_the_estate_does_not_populate():
    """The structural half of "which monitors can never fire here?"."""
    r = rp.run(_ctx(), ids=["ops-silent-monitors"])["reports"][0]
    assert r["summary"]["silent"] > 0
    assert all(row["evidence"] == "structural" for row in r["rows"])


def test_noisy_monitors_flags_a_deliberately_noisy_design():
    ctx = _ctx()
    inst = next(i for i in ctx.instances)
    arch = dict(ctx.arch(inst["archetype"]),
                signal="latency", detection="threshold", query="avg:x{*}",
                group_by=["a", "b"], notify_by=[], evaluation_window="last_5m")
    score, reasons = rp.noise_risk(POLICY, arch, dict(inst, pages=False))
    assert score >= 3
    assert any("collapse key" in x for x in reasons)


def test_flapping_flags_a_behavioural_threshold_with_no_recovery_band():
    arch = {"signal": "latency", "detection": "threshold", "thresholds": {"critical": 1},
            "evaluation_window": "last_5m"}
    assert rp.flap_risk(POLICY, arch)
    # A recovery band is exactly the fix, so declaring one must clear the finding.
    healthy = dict(arch, thresholds={"critical": 1, "critical_recovery": 0.8},
                   evaluation_window="last_30m")
    assert rp.flap_risk(POLICY, healthy) == []


def test_a_forecast_window_is_never_called_flap_prone():
    """`next_1w` asserts nothing about right now, so it cannot oscillate."""
    assert rp.window_minutes("next_1w") is None
    assert rp.window_minutes("last_3_checks") is None
    assert rp.window_minutes("last_2h") == 120


def test_oncall_coverage_catches_a_team_with_no_rotation():
    ctx = _ctx()
    # Take the rotation away from a team that owns paging monitors: the report
    # must notice, because a paging monitor with no rotation is a page into the
    # void and looks fully covered on every other report in this repository.
    paging_team = next(t["team"] for _, t in ctx.monitor_rows()
                       if t.get("pages") == "true")
    ctx.policy = dict(POLICY, teams=dict(
        POLICY["teams"], **{paging_team: dict(POLICY["teams"][paging_team], oncall=False)}))
    r = rp.REPORTS["ops-oncall-coverage"](ctx)
    row = next(x for x in r["rows"] if x["team"] == paging_team)
    assert any("no rotation" in p for p in row["problems"])


def test_oncall_coverage_is_clean_on_the_committed_policy():
    r = rp.REPORTS["ops-oncall-coverage"](_ctx())
    assert r["summary"]["needing_attention"] == 0, r["rows"]
    assert r["summary"]["paging_monitors"] > 0


def test_runbook_coverage_sees_every_monitor_as_attached():
    """C16 in the coverage report and this report must not disagree."""
    r = rp.REPORTS["ops-runbook-coverage"](_ctx())
    assert r["summary"]["monitors_without_an_attached_notebook"] == 0
    assert r["summary"]["runbooks_with_unfinished_sections"] == 0


def test_runbook_coverage_notices_an_unattached_notebook():
    stripped = [dict(m, tags=[t for t in m["tags"]
                              if not t.startswith("runbook_notebook:")])
                for m in MONITORS[:20]] + MONITORS[20:]
    r = rp.REPORTS["ops-runbook-coverage"](_ctx(monitors=stripped))
    assert r["summary"]["monitors_without_an_attached_notebook"] == 20


def test_missing_ownership_separates_the_pool_from_an_inferred_default():
    """An inferred owner is not an owner, and the two are not the same finding."""
    r = rp.REPORTS["ops-missing-ownership"](_ctx())
    assert "resources_in_unowned_pool" in r["summary"]
    assert r["summary"]["unowned_pool_sla_days"] == \
        POLICY["teams_doc"]["unowned_pool"]["max_age_days"]


def test_durability_report_names_the_technologies_with_no_horizon():
    r = rp.REPORTS["db-durability"](_ctx())
    gaps = [x["resource_type"] for x in r["rows"] if not x["durability_covered"]]
    assert gaps, "the durability report must be able to find a gap"
    # Every gap is a datastore technology, never a service or a host: the whole
    # point of the entity model is that this question is not asked of them.
    for rt in gaps:
        assert oc.entity_kind(POLICY, rt) == "datastore"


def test_infra_fleet_health_only_grades_infrastructure():
    r = rp.REPORTS["infra-fleet-health"](_ctx())
    for row in r["rows"]:
        assert oc.entity_kind(POLICY, row["resource_type"]) == "infrastructure"


def test_estate_budget_matches_the_policy_budget():
    r = rp.REPORTS["plat-estate-budget"](_ctx())
    limits = {x["budget"]: x["limit"] for x in r["rows"]}
    card = POLICY["global"]["cardinality"]
    assert limits["managed monitor patterns"] == card["max_total_managed_monitors"]
    assert limits["paging patterns"] == card["max_paging_monitors"]
    assert not any(x["over"] for x in r["rows"]), "the estate is over budget"


def test_reports_never_grade_click_ops_monitors():
    """Grading a monitor this platform did not write produces findings nobody
    can fix; click-ops monitors are counted by the coverage report instead."""
    rogue = MONITORS + [{"id": 999999, "name": "hand-made", "tags": ["env:prod"],
                         "query": "avg:x{*} > 1", "message": "", "options": {}}]
    ctx = _ctx(monitors=rogue)
    assert 999999 not in ctx.managed
    assert all(m["id"] != 999999 for m, _ in ctx.monitor_rows())


# --- §35 the survey ----------------------------------------------------------

SURVEY = Path(__file__).resolve().parents[1] / "docs" / "observability-survey.md"


def test_the_survey_exists_and_is_short():
    """§35 asks for a SHORT questionnaire. A survey that grows to sixty
    questions is a service-design workshop, which is exactly what the policy
    engine exists to make unnecessary."""
    text = SURVEY.read_text()
    questions = [ln for ln in text.splitlines() if ln.startswith("### ")]
    assert 0 < len(questions) <= 20, f"{len(questions)} questions is too many"


def test_every_survey_question_says_why_it_cannot_be_inferred():
    """The standing rule: a question that IS inferable gets deleted."""
    text = SURVEY.read_text()
    blocks = text.split("### ")[1:]
    for b in blocks:
        head = b.splitlines()[0]
        assert "Why we cannot infer it" in b, (
            f"survey question {head!r} does not say why it cannot be inferred")


def test_the_survey_does_not_ask_what_policy_already_decides():
    """Asking invites an answer that contradicts the policy and then has to be
    argued back down."""
    body = SURVEY.read_text().split("## What this survey deliberately does not ask")[0]
    questions = "\n".join(ln for ln in body.splitlines() if ln.startswith("### ")).lower()
    for banned in ("what threshold", "which channel", "what dashboards",
                   "which dashboards", "what do you want to monitor"):
        assert banned not in questions, f"the survey asks {banned!r}, which is derived"


# --- §33 the dashboard budget ------------------------------------------------

DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "stacks" / "foundation" / "dashboards"


def test_the_estate_holds_at_most_four_dashboards():
    """§33 asks for ~4 and the platform ships 3. The per-domain generator is
    gone: a domain view is the native monitor list filtered by `domain:`, and a
    generated copy is a snapshot of what we knew on the day it was generated."""
    boards = sorted(p.name for p in DASHBOARD_DIR.glob("*.json"))
    assert len(boards) <= 4, boards
    assert not list(DASHBOARD_DIR.glob("*.tftpl")), (
        "a dashboard template is a per-object generator waiting to be re-enabled")


def test_every_dashboard_is_valid_json_and_declares_its_management():
    for p in sorted(DASHBOARD_DIR.glob("*.json")):
        board = json.loads(p.read_text())
        assert board["title"], p.name
        assert "Managed by Terraform" in board["description"], p.name
        assert board["widgets"], p.name


def test_the_three_surviving_boards_are_the_ones_the_requirement_names():
    titles = {json.loads(p.read_text())["title"]
              for p in DASHBOARD_DIR.glob("*.json")}
    assert titles == {"Enterprise Observability Overview",
                      "Operations & Reliability",
                      "SLO & Executive Health"}, titles
