"""CATALOG RECONCILIATION (§6) — is everything deployed something we declared?

Coverage checks ask the forward question: is everything we declared deployed?
This asks the mirror image, and the failure it prevents is subtler than a
missing monitor. A catalog carrying entries nothing owns still looks like a
catalog — same list, same shape, same apparent authority — so nobody discovers
it is wrong until they trust one of the entries during an incident.

The assertions that matter most here are the ones about NOT deleting.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pytest                                          # noqa: E402

import catalog_reconcile as cr                         # noqa: E402
import obs_common as oc                                # noqa: E402

POLICY = oc.load_policy()


def svc(name, links=()):
    return {"name": name, "team": "t", "description": "", "links": list(links)}


def nb(nb_id, name, author="someone"):
    return {"id": str(nb_id), "name": name, "author": author, "modified": ""}


def a_registered_runbook():
    """A runbook that IS in the registry, with its id and its published name."""
    for rid, r in POLICY["runbooks"].items():
        if r.get("id"):
            return str(r["id"]), f"Runbook: {r.get('title', rid)}"
    pytest.skip("no runbook has a published id")


# --- services ----------------------------------------------------------------

def test_a_registered_entity_is_managed():
    name = sorted(oc.load_entities())[0]
    row = cr.reconcile([svc(name)], [])["services"][0]
    assert row["verdict"] == "managed"


def test_an_entry_from_another_repository_is_unmanaged_and_says_which():
    """Provenance comes from the entry's own registry link, not from the shape
    of its name — an inference from naming would be a guess about somebody
    else's convention."""
    row = cr.reconcile(
        [svc("qis_service", ["https://github.com/someone-else/their-iac/blob/main/x.yml"])],
        [])["services"][0]
    assert row["verdict"] == "unmanaged"
    assert "someone-else/their-iac" in row["reason"]


def test_our_own_repository_link_is_not_treated_as_foreign():
    own = POLICY["global"]["org"]["repo"]
    row = cr.reconcile([svc("not-registered", [f"https://github.com/{own}/blob/main/x"])],
                       [])["services"][0]
    assert row["verdict"] == "unmanaged"          # still unmanaged: no entity file
    assert "points at" not in row["reason"]       # but not blamed on another repo


def test_datadog_created_services_are_neither_managed_nor_drift():
    """`github-actions` is created by Datadog from CI traffic and returns after
    deletion. Reporting it as drift every run is how a report becomes noise."""
    r = cr.reconcile([svc("github-actions")], [])
    assert r["services"][0]["verdict"] == "auto_created"
    assert r["summary"]["services_unmanaged"] == 0


# --- notebooks ---------------------------------------------------------------

def test_a_notebook_whose_id_is_registered_is_managed():
    nb_id, name = a_registered_runbook()
    assert cr.reconcile([], [nb(nb_id, name)])["notebooks"][0]["verdict"] == "managed"


def test_a_published_runbook_missing_from_the_committed_registry_is_still_managed():
    """THE ONE THAT PREVENTS DATA LOSS.

    publish_runbooks writes ids into runbooks.yaml in the CI checkout, which is
    then discarded, so the committed registry always trails production by
    however many runbooks were added since someone last committed it back.
    Matching on id alone would classify the NEWEST runbooks — published minutes
    earlier by the deploy that created them — as unmanaged, and `--delete`
    would remove them.
    """
    _, name = a_registered_runbook()
    r = cr.reconcile([], [nb("999999999", name)])
    row = r["notebooks"][0]
    assert row["verdict"] == "managed_by_name"
    assert "not committed yet" in row["reason"]
    assert r["summary"]["notebooks_unmanaged"] == 0
    assert r["summary"]["notebooks_managed"] == 1
    # And the drift is COUNTED, not silently absorbed — otherwise "the name
    # fallback saves us" quietly becomes "nobody ever commits the registry".
    assert r["summary"]["notebooks_published_but_unrecorded"] == 1


def test_a_notebook_nobody_registered_is_unmanaged():
    row = cr.reconcile([], [nb("42", "Some AI-generated notebook", "dd-ai-start")])["notebooks"][0]
    assert row["verdict"] == "unmanaged"
    assert "dd-ai-start" in row["reason"]


# --- the safety rails --------------------------------------------------------

def test_deleting_more_than_the_cap_is_refused():
    """A reconciler that deletes hundreds of objects because a path changed is
    worse than the drift it was fixing."""
    report = cr.reconcile([svc(f"stale-{i}") for i in range(50)], [])
    with pytest.raises(SystemExit) as e:
        cr.delete_unmanaged(report, "https://api.example", {},
                            kinds={"services"}, max_delete=40)
    assert "refusing to delete 50" in str(e.value)


def test_kinds_scopes_what_is_deleted(monkeypatch):
    """Asking for one kind must not quietly take the other with it."""
    called = []
    monkeypatch.setattr(cr.oc, "dd_request",
                        lambda m, url, **kw: called.append(url) or type(
                            "R", (), {"status_code": 204, "text": ""})())
    report = cr.reconcile([svc("stale-svc")], [nb("7", "Unregistered notebook")])
    cr.delete_unmanaged(report, "https://api.example", {},
                        kinds={"notebooks"}, max_delete=40)
    assert len(called) == 1 and "/notebooks/7" in called[0]


def test_one_failed_deletion_does_not_abandon_the_rest(monkeypatch):
    def fake(method, url, **kw):
        if "stale-b" in url:
            return type("R", (), {"status_code": 409, "text": "referenced"})()
        return type("R", (), {"status_code": 204, "text": ""})()

    monkeypatch.setattr(cr.oc, "dd_request", fake)
    report = cr.reconcile([svc("stale-a"), svc("stale-b"), svc("stale-c")], [])
    out = cr.delete_unmanaged(report, "https://api.example", {},
                              kinds={"services"}, max_delete=40)
    assert len(out["deleted"]) == 2 and len(out["failed"]) == 1
    assert out["failed"][0]["status"] == 409


def test_the_markdown_names_every_unmanaged_object():
    md = cr.to_markdown(cr.reconcile(
        [svc("stale-svc", ["https://github.com/elsewhere/iac/x.yml"])],
        [nb("7", "Unregistered notebook")]))
    assert "stale-svc" in md and "Unregistered notebook" in md
