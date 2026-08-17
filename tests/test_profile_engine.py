"""Profile engine: policy assignment correctness + million-resource scale."""
import time

import build_inventory
import obs_common as oc
import profile_engine


def _policy():
    return oc.load_policy()


def _assign(resources):
    inv = {"resources": resources, "resource_count": len(resources)}
    return profile_engine.assign(inv, _policy())


def test_prod_tier1_gets_critical_profile():
    res = _assign([{
        "id": "service:x", "kind": "service", "name": "x", "env": "prod",
        "service": "x", "team": "sre",
        "tags": {"env": "prod", "criticality": "tier1", "team": "sre"},
    }])
    a = res["assignments"][0]
    assert a["monitoring_profile"] == "critical"
    assert a["owner_source"] == "tag"
    assert not a["violations"]


def test_sandbox_is_observe_only_with_reason():
    res = _assign([{
        "id": "host:h1", "kind": "host", "name": "h1", "env": "sandbox",
        "service": "s", "team": "sre", "tags": {"env": "sandbox", "team": "sre", "criticality": "tier2"},
    }])
    a = res["assignments"][0]
    assert a["monitoring_profile"] == "observe_only"
    assert a["observe_only_reason"]  # explicit, policy-driven, reported


def test_security_domain_forced_security_sensitive():
    res = _assign([{
        "id": "log_source:fw", "kind": "log_source", "name": "fw", "env": "prod",
        "service": "security-telemetry", "team": "security",
        "tags": {"env": "prod", "team": "security", "criticality": "tier2"},
    }])
    assert res["assignments"][0]["monitoring_profile"] == "security_sensitive"


def test_missing_owner_falls_back_and_flags():
    res = _assign([{
        "id": "host:h2", "kind": "host", "name": "h2", "env": "prod",
        "service": "y", "team": None, "tags": {"env": "prod", "criticality": "tier2"},
    }])
    a = res["assignments"][0]
    assert a["team"] == "infrastructure-engineering"  # domain default owner
    assert any(v.startswith("owner_inferred") for v in a["violations"])


def test_exception_grants_observe_only():
    # EXC-2026-001: efront_bts_int prod → observe_only
    res = _assign([{
        "id": "service:efront_bts_int", "kind": "service", "name": "efront_bts_int",
        "env": "prod", "service": "efront_bts_int", "team": "application-development",
        "tags": {"env": "prod", "team": "application-development", "criticality": "tier2"},
    }])
    a = res["assignments"][0]
    assert a["monitoring_profile"] == "observe_only"
    assert "EXC-2026-001" in (a["observe_only_reason"] or "")


def test_invalid_env_flagged_not_dropped():
    res = _assign([{
        "id": "host:h3", "kind": "host", "name": "h3", "env": "production",
        "service": "z", "team": "sre", "tags": {"env": "production", "team": "sre"},
    }])
    a = res["assignments"][0]
    assert any(v.startswith("invalid_env") for v in a["violations"])
    assert a["monitoring_profile"] != "observe_only"  # unknown env treated as prod


def test_scale_1_2_million_resources():
    """The estate target: >1M resources, ~100k services, bounded runtime.

    Every resource must end up with owner, env, criticality and profile —
    the '100% inventory coverage' invariant at design scale.
    """
    n = 1_200_000
    resources = build_inventory.synthesize(n)
    services = {r["service"] for r in resources}
    assert len(services) >= 100_000

    t0 = time.time()
    res = _assign(resources)
    elapsed = time.time() - t0

    s = res["summary"]
    assert s["total"] == n
    # invariant: nothing is left unassigned
    assert sum(s["by_profile"].values()) == n
    for a in res["assignments"][:1000]:
        assert a["team"] and a["criticality"] and a["monitoring_profile"] and a["env"]
    # deliberately-broken 3% appear as violations, not silent gaps
    assert s["with_violations"] > 0
    # single-threaded policy pass must stay operationally cheap
    assert elapsed < 120, f"profile engine too slow at scale: {elapsed:.1f}s"
