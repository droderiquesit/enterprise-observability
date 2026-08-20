"""Scorecard, generated documentation, and runbook completeness.

The generated artefacts are tested for FRESHNESS, not just correctness. A
coverage matrix that no longer matches the catalog is worse than no matrix,
because people trust it.
"""
from pathlib import Path

import generate_matrix
import generate_runbooks
import monitor_scorecard as ms
import obs_common as oc
import publish_runbooks as pr

POLICY = oc.load_policy()


# --- scorecard --------------------------------------------------------------

def test_fleet_scores_at_least_an_a():
    report = ms.build(POLICY)
    assert report["summary"]["fleet_grade"] in ("A", "B")
    assert report["summary"]["failing"] == 0


def test_every_team_has_a_score():
    report = ms.build(POLICY)
    owning = {POLICY["domains"][d].get("routing_override_team",
                                       POLICY["domains"][d]["owner_team"])
              for d in POLICY["domains"]}
    for team in owning:
        assert team in report["by_team"], f"{team} owns monitors but has no score"


def test_scorecard_punishes_a_monitor_that_pages_from_staging():
    inst = next(i for i in oc.expand_instances(POLICY) if i["env"] == "stage")
    inst = dict(inst, pages=True)
    row = ms.score_instance(POLICY, inst, POLICY["archetypes"][inst["archetype"]])
    assert row["dimensions"]["paging"] == 0
    assert any("pages in stage" in f for f in row["findings"])


def test_scorecard_punishes_an_unresolvable_slo():
    inst = next(iter(oc.expand_instances(POLICY)))
    arch = dict(POLICY["archetypes"][inst["archetype"]])
    row = ms.score_instance(POLICY, dict(inst, slo_id="slo-does-not-exist"), arch)
    assert row["dimensions"]["slo_linkage"] == 0


def test_self_service_monitors_are_scored_too():
    """platform/monitors/ is deliberately empty — a file there is DEPLOYED, so
    an example living there would be an artificial monitor in production. The
    scorer is exercised against the reference manifest fixture instead, which
    keeps the self-service scoring path covered without shipping an example."""
    import yaml
    fixture = Path(__file__).parent / "fixtures" / "self_service_example.yaml"
    m = yaml.safe_load(fixture.read_text())["monitor"]
    row = ms.score_custom(POLICY, m["name"], m, oc.load_services())
    assert row["monitor_id"].startswith("custom.")
    assert row["score"] > 0


# --- generated documentation ------------------------------------------------

def test_coverage_matrix_is_not_stale():
    """CI runs exactly this: the committed matrix must match the catalog."""
    rendered = generate_matrix.render(POLICY, generate_matrix.build(POLICY))
    assert generate_matrix.MATRIX_PATH.read_text() == rendered, (
        "docs/monitor-coverage-matrix.md is stale — run tools/generate_matrix.py")


def test_matrix_covers_every_domain():
    rows = generate_matrix.build(POLICY)
    assert {r["domain"] for r in rows} == set(POLICY["domains"])


def test_matrix_row_count_matches_the_planned_estate():
    assert len(generate_matrix.build(POLICY)) == len(oc.expand_instances(POLICY))


# --- runbooks ---------------------------------------------------------------

def test_every_archetype_reaches_a_runbook_file():
    """Via its runbook id, which an archetype may SHARE with another (
    api-latency-seasonal points at api-latency-p99). The file is named for the
    runbook, not for the archetype."""
    for aid, a in POLICY["archetypes"].items():
        assert (generate_runbooks.RUNBOOK_DIR / f"{a['runbook']}.md").exists(), aid


def test_every_runbook_has_all_mandatory_sections():
    for path in sorted(generate_runbooks.RUNBOOK_DIR.glob("*.md")):
        assert pr.validate_template(path.read_text()) == [], path.name


def test_runbook_registry_and_files_agree():
    files = {p.stem for p in generate_runbooks.RUNBOOK_DIR.glob("*.md")}
    registry = set(POLICY["runbooks"])
    assert files == registry, f"only in files: {files - registry}; only in registry: {registry - files}"


def test_runbook_drafts_are_not_stale():
    for aid, a in POLICY["archetypes"].items():
        if a["runbook"] != aid:
            continue          # shared runbook — owned and rendered by its own archetype
        path = generate_runbooks.RUNBOOK_DIR / f"{aid}.md"
        generated = generate_runbooks.render(POLICY, aid, a)
        assert path.read_text() == generate_runbooks.merge(path.read_text(), generated), (
            f"{aid}.md generated block is stale — run tools/generate_runbooks.py")


def test_runbook_render_is_deterministic_and_hashed():
    src = (generate_runbooks.RUNBOOK_DIR / "slo-error-budget-burn.md").read_text()
    assert pr.render_cells(src) == pr.render_cells(src)
    assert "content_hash:" in pr.render_cells(src)[-1]["attributes"]["definition"]["text"]


def test_editing_a_runbook_changes_its_hash():
    src = (generate_runbooks.RUNBOOK_DIR / "slo-error-budget-burn.md").read_text()
    assert pr.content_hash(src) != pr.content_hash(src + "\nan edit\n")


def test_incomplete_runbook_is_rejected():
    one = pr.REQUIRED_SECTIONS[0]
    assert len(pr.validate_template(f"# Runbook: X\n## {one}\nonly one section")) == \
        len(pr.REQUIRED_SECTIONS) - 1


# --- the runbook is an ATTACHABLE Datadog object, not a document reference ----

def test_no_runbook_contains_a_placeholder():
    """A runbook attached to a monitor promises a responder will find
    instructions. A stub keeps the promise's shape and drops its content."""
    for path in sorted(generate_runbooks.RUNBOOK_DIR.glob("*.md")):
        assert pr.unfinished_sections(path.read_text()) == 0, (
            f"{path.name} still contains a placeholder marker")


def test_every_runbook_carries_every_required_section():
    for path in sorted(generate_runbooks.RUNBOOK_DIR.glob("*.md")):
        assert pr.validate_template(path.read_text()) == [], path.name


def test_runbooks_are_not_repository_links():
    """No runbook may point a responder back at the repository: the published
    notebook is the artifact, and a GitHub blob is unreachable from Datadog."""
    doc = POLICY["runbooks_doc"]
    assert "docs_base_url" not in doc, (
        "docs_base_url resurrects repository links as runbooks")
    assert doc["notebook_base_url"].startswith("https://app.datadoghq.com"), doc


def test_registry_ids_are_numeric_notebook_references():
    for rid, r in POLICY["runbooks"].items():
        if r.get("id") is not None:
            assert str(r["id"]).isdigit(), f"{rid}: id must be a notebook id, got {r['id']!r}"


def test_review_date_is_deterministic():
    """A runbook that rewrites itself daily cannot be staleness-checked."""
    first = generate_runbooks.review_date(POLICY, "quarterly")
    assert first == generate_runbooks.review_date(POLICY, "quarterly")
    assert len(first) == 10 and first[4] == "-"
