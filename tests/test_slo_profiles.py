"""SLO PROFILES, THE RESOLUTION CHAIN, AND SLO/CATALOG INTEGRITY (§11–§15).

The claim under test is narrow and load-bearing: a service states its INTENT,
and the platform resolves the objectives. Two services can therefore be
identical in every technical respect — same archetype, same monitors, same
routing — and still owe different promises, which is the §59 proof at the
bottom of this file.

The fixture services in tests/fixtures/slo_services/ are deliberately NOT in
platform/services/: a file there is deployed, and a proof must not create
objectives in a real Datadog organization.
"""
import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

import coverage_report as cr
import obs_common as oc
import slo_resolver as sr

FIXTURES = Path(__file__).parent / "fixtures"
POLICY = oc.load_policy()
DOC = POLICY["slo_profiles_doc"]
REGISTERED = oc.load_services()
SLOS = json.loads((FIXTURES / "slos.json").read_text())


def _fixture_services() -> dict:
    out = {}
    for f in sorted((FIXTURES / "slo_services").glob("*.yaml")):
        svc = yaml.safe_load(f.read_text())["service"]
        out[svc["name"]] = svc
    return out


SERVICES = _fixture_services()


def _resolve(name, env="prod"):
    return sr.resolve_objectives(POLICY, SERVICES[name], env)


def _slos(name):
    return sr.resolved_slos(POLICY, {name: SERVICES[name]})


# --- the catalog itself ------------------------------------------------------

def test_the_profile_catalog_is_valid():
    """Same rules CI runs; asserted here so a broken profile fails the suite
    rather than only the linter."""
    assert sr.validate(POLICY, {**REGISTERED, **SERVICES}) == []


def test_fixture_services_satisfy_the_registration_schema():
    """The proof services must be things the platform would really accept —
    otherwise the proof is about a shape nobody can register."""
    schema = json.loads((oc.PLATFORM_DIR / "schemas" / "service.schema.json").read_text())
    for f in sorted((FIXTURES / "slo_services").glob("*.yaml")):
        jsonschema.validate(yaml.safe_load(f.read_text()), schema)


def test_objective_names_are_the_ones_the_tiers_carry():
    """The criticality layer is tiers.yaml. An objective name it does not know
    is an objective with no business target, and the chain would fall through
    to whatever number a profile happened to write."""
    tier_objectives = set()
    for tier in POLICY["tiers"].values():
        tier_objectives |= set(tier["slo"].get("objectives") or {})
    assert set(DOC["objective_names"]) == tier_objectives


def test_every_profile_can_be_applied_to_something():
    for pid, profile in DOC["profiles"].items():
        assert profile.get("entity_types"), pid
        for et in profile["entity_types"]:
            assert et in POLICY["service_archetypes"], f"{pid} → {et}"


# --- the chain, layer by layer ----------------------------------------------

def test_a_registered_tier0_service_resolves_what_it_resolved_before_profiles():
    """The regression guard on the whole phase.

    identity-api names no profile. It must still resolve exactly one objective,
    at the tier target, on the tier's burn windows, under the id it is already
    deployed with — because an SLO recreated is an error-budget history erased.
    """
    slos = sr.resolved_slos(POLICY, {"identity-api": REGISTERED["identity-api"]})
    assert list(slos) == ["slo-svc-identity-api"]
    slo = slos["slo-svc-identity-api"]
    assert slo["target"] == POLICY["tiers"]["tier0"]["slo"]["objectives"]["availability"]
    assert slo["type"] == "metric"
    assert slo["timeframe"] == "30d"
    assert slo["burn_alerts"] == POLICY["tiers"]["tier0"]["slo"]["burn_windows"]


def test_each_layer_is_overridden_by_the_next():
    """The chain, asserted as an ordering rather than as four separate numbers."""
    # enterprise default → entity type turns availability on for anything that
    # serves requests, whether or not the service ever names a profile
    bare = sr.resolve_objectives(POLICY, REGISTERED["identity-api"])["availability"]
    assert bare["provenance"]["enabled"] == "entity_type"

    default = _resolve("internal-orders-api")["availability"]
    # entity type → platform replaces the SLI (health routes excluded)
    assert default["provenance"]["sli.numerator"] == "platform"
    assert "!http.route:/health" in default["query"]["numerator"]
    # criticality → profile: api-standard's 99.9 beats tier0's 99.95
    assert default["provenance"]["target"] == "slo_profile"
    assert default["target"] == 99.9
    # profile → service override
    override = _resolve("partner-orders-api")["availability"]
    assert override["provenance"]["target"] == "service_override"
    assert override["target"] == 99.99


def test_the_tier_sets_the_target_when_no_profile_does():
    svc = dict(SERVICES["internal-orders-api"])
    svc.pop("slo")
    obj = sr.resolve_objectives(POLICY, svc)["availability"]
    assert obj["provenance"]["target"] == "criticality"
    assert obj["target"] == POLICY["tiers"]["tier0"]["slo"]["objectives"]["availability"]


def test_non_production_never_materializes_an_objective():
    """An error budget is a promise to customers, and environments.yaml gives
    only prod `slo_impact`. The reason must be visible in the provenance, not
    inferred from an absence."""
    for env in ("dev", "qa", "stage"):
        for obj in _resolve("partner-orders-api", env).values():
            assert obj["enabled"] is False
            assert obj["provenance"]["enabled"] == "environment"


def test_an_objective_an_entity_type_declares_is_not_an_objective_it_owes():
    """`enabled` is the difference between "an API could have a latency
    objective" and "this service promised one" — and the reason a tier0 service
    that names no profile gets one SLO, not three."""
    resolved = sr.resolve_objectives(POLICY, REGISTERED["identity-api"])
    assert resolved["availability"]["enabled"] is True
    assert resolved["latency"]["enabled"] is False
    assert set(resolved) == {"availability", "latency"}


def test_a_threshold_override_keeps_the_fields_it_did_not_state():
    """partner-orders-api overrides only the latency VALUE. Replacing the whole
    threshold map would drop the statistic and the unit, and the SLI would read
    a bucket tag nobody emits."""
    latency = _resolve("partner-orders-api")["latency"]
    assert latency["threshold"] == {"statistic": "p99_duration", "operator": "<",
                                    "value": 200, "unit": "ms"}
    assert latency["provenance"]["threshold.value"] == "service_override"
    assert "latency_bucket:under_200ms" in latency["query"]["numerator"]


def test_the_latency_boundary_reaches_the_sli():
    """Two services with different latency promises must not read the same
    bucket tag, or the threshold is decoration."""
    partner = _resolve("partner-orders-api")["latency"]["query"]["numerator"]
    internal = _resolve("internal-orders-api")["latency"]["query"]["numerator"]
    assert "under_200ms" in partner
    assert "under_800ms" in internal


def test_every_resolved_sli_is_fully_substituted():
    for name in SERVICES:
        for slo_id, slo in _slos(name).items():
            for side, q in (slo["query"] or {}).items():
                assert "__" not in q, f"{slo_id} {side}: {q}"
                assert name in q


def test_a_service_check_objective_cannot_carry_burn_alerts():
    """An INVARIANT, not a layer: Datadog rejects burn_rate() on a monitor SLO
    with a non-metric member ("Alerting on monitor based SLOs currently supports
    metric monitors" — found by live plan validation). tier0 asks for three burn
    windows; the datastore gets none, and the reason is recorded."""
    availability = _resolve("orders-sql")["availability"]
    assert availability["type"] == "monitor"
    assert availability["burn_alerts"] == []
    assert availability["provenance"]["burn_alerts"] == "invariant:non_metric_members"
    assert any("burn_rate" in w or "metric monitors" in w for w in availability["warnings"])


def test_the_entity_type_decides_which_objectives_exist_at_all():
    """A batch job has no request ratio and no percentile; it owes a completed
    run and a fresh output. The old single template measured every tier0 service
    with an HTTP SLI, which is how an SLO ends up permanently green."""
    batch = {o["objective"] for o in _slos("settlement-batch").values()}
    api = {o["objective"] for o in _slos("partner-orders-api").values()}
    assert batch == {"availability", "freshness"}
    assert api == {"availability", "latency"}


# --- §14 — not every entity needs an SLO ------------------------------------

def test_a_tier2_service_carries_no_objectives_of_its_own():
    assert sr.resolved_slos(POLICY, {"reporting-portal": REGISTERED["reporting-portal"]}) == {}


def test_a_lower_tier_service_can_opt_in_by_declaring_one():
    """tier1's scope is `domain`, so settlement-batch would have none.
    `slo.scope: per_service` is the opt-in — a service with one contractual
    output should not have to be relabelled tier0 to make a promise.

    The opt-in is that VALUE. Testing for the mere presence of an `slo:` block
    opted IN every service that declared `scope: domain` to decline one."""
    assert SERVICES["settlement-batch"]["tier"] == "tier1"
    assert POLICY["tiers"]["tier1"]["slo"]["scope"] == "domain"
    assert sr.materializes_per_service_slos(POLICY, SERVICES["settlement-batch"])
    assert len(_slos("settlement-batch")) == 2


# --- identity ----------------------------------------------------------------

def test_the_availability_objective_keeps_its_historical_id():
    """Renaming an SLO in Datadog destroys and recreates it, taking the error
    budget history with it. Availability keeps `slo-svc-<service>`; every
    objective this phase adds takes a suffix."""
    assert sr.slo_id_for("orders-api", "availability") == "slo-svc-orders-api"
    assert sr.slo_id_for("orders-api", "latency") == "slo-svc-orders-api-latency"


def test_resolved_slo_ids_are_unique_across_services():
    ids = [i for name in SERVICES for i in _slos(name)]
    assert len(ids) == len(set(ids))


# --- the two implementations of the chain must not drift --------------------

SLOS_TF = (Path(__file__).parent.parent / "stacks" / "coverage" / "slos.tf").read_text()

# How each layer appears in the HCL try-chains. Terraform resolves the chain for
# the apply and this module resolves it for the tooling; both read the same YAML
# and neither reads the other, so the ONE thing that can silently diverge is the
# order of the layers.
HCL_LAYER_MARKERS = {
    "v.svc.slo.objectives[": "service_override",
    "slo_profiles.profiles[": "slo_profile",
    "local.tiers[": "criticality",
    "slo_profiles.by_platform[": "platform",
    "slo_profiles.by_entity_type[": "entity_type",
    "slo_profiles.defaults": "enterprise_defaults",
}


@pytest.mark.parametrize("field", ["enabled", "type", "target", "timeframe", "burn_alerts"])
def test_terraform_resolves_the_layers_in_the_same_order(field):
    """`try()` returns the first expression that succeeds, so an HCL chain is
    the layer order written backwards. Read it back and check it against
    slo_resolver.LAYERS — a reordered chain is a silent policy change that no
    plan diff would explain."""
    block = SLOS_TF.split(f"\n      {field} = try(", 1)[1].split("\n\n", 1)[0]
    seen = [layer for _, layer in
            sorted((block.index(marker), layer)
                   for marker, layer in HCL_LAYER_MARKERS.items() if marker in block)]
    ranks = [sr.LAYERS.index(layer) for layer in seen]
    assert len(ranks) >= 3, f"{field} resolves from too few layers to be a chain"
    assert ranks == sorted(ranks, reverse=True), f"{field}: {seen}"


def test_terraform_spells_the_latency_bucket_tag_the_same_way():
    """The threshold reaches the SLI as a tag value. If the two implementations
    spell it differently, the plan and the tooling disagree about which series
    the objective reads, and only one of them is deployed."""
    assert sr.latency_bucket({"value": 300, "unit": "ms"}) == "under_300ms"
    assert '"under_${r.threshold_value}${r.threshold_unit}"' in SLOS_TF


# =============================================================================
# §59 PROOF — two technically identical services, two different promises
# =============================================================================

def test_two_identical_services_receive_their_own_correct_slos():
    partner, internal = SERVICES["partner-orders-api"], SERVICES["internal-orders-api"]

    # 1. They are the same thing to the MONITORING side of the platform: the
    #    same entity type selects the same packs, and the same tier resolves the
    #    same band, support model and paging policy. Nothing below changes any
    #    monitor, which is the whole point.
    assert partner["service_archetype"] == internal["service_archetype"]
    assert partner["tier"] == internal["tier"]
    assert partner["team"] == internal["team"]
    packs = POLICY["service_archetypes"][partner["service_archetype"]]["packs"]
    assert POLICY["service_archetypes"][internal["service_archetype"]]["packs"] == packs
    assert cr._covering_archetypes(POLICY, partner["service_archetype"]) == \
        cr._covering_archetypes(POLICY, internal["service_archetype"])

    # 2. They owe different promises, and each gets its own objects.
    p = _slos("partner-orders-api")
    i = _slos("internal-orders-api")
    assert set(p) == {"slo-svc-partner-orders-api", "slo-svc-partner-orders-api-latency"}
    assert set(i) == {"slo-svc-internal-orders-api", "slo-svc-internal-orders-api-latency"}

    assert p["slo-svc-partner-orders-api"]["target"] == 99.99
    assert i["slo-svc-internal-orders-api"]["target"] == 99.9
    assert p["slo-svc-partner-orders-api-latency"]["target"] == 99.5
    assert i["slo-svc-internal-orders-api-latency"]["target"] == 99.0

    # 3. And different burn behaviour: the partner objective pages on a medium
    #    burn, the internal one never does.
    assert p["slo-svc-partner-orders-api"]["burn_alerts"] == ["fast", "medium", "slow"]
    assert i["slo-svc-internal-orders-api"]["burn_alerts"] == ["fast", "slow"]

    # 4. Each SLO is measured against its OWN service, not the other's.
    for slo_id, slo in {**p, **i}.items():
        assert slo["service"] in slo["query"]["numerator"]
        other = "internal" if "partner" in slo_id else "partner"
        assert other not in slo["query"]["numerator"]

    # 5. The difference is attributable: every field that differs names the
    #    layer that decided it.
    assert p["slo-svc-partner-orders-api"]["provenance"]["target"] == "service_override"
    assert i["slo-svc-internal-orders-api"]["provenance"]["target"] == "slo_profile"


def test_the_same_two_services_are_indistinguishable_without_their_slo_block():
    """The control for the proof above: strip the `slo:` blocks and the two
    services resolve identically, which is what makes the difference come from
    the declaration and nothing else."""
    def stripped(name):
        svc = {k: v for k, v in SERVICES[name].items() if k != "slo"}
        return [(o["objective"], o["target"], o["type"], o["timeframe"], tuple(o["burn_alerts"]))
                for o in sr.resolved_slos(POLICY, {name: svc}).values()]

    assert stripped("partner-orders-api") == stripped("internal-orders-api")


# =============================================================================
# §15 — monitor-to-SLO governance classification
# =============================================================================

RELATIONS = DOC["slo_relations"]
MONITOR_SLO_MEMBERS = {
    m for s in POLICY["slos"].values() if s["type"] == "monitor"
    for m in s.get("member_archetypes", [])
}


def test_every_archetype_states_how_it_relates_to_an_objective():
    for aid, a in POLICY["archetypes"].items():
        assert a.get("slo_relation"), f"{aid} names an SLO but not its relation to it"
        assert a["slo_relation"] in RELATIONS, f"{aid}: {a['slo_relation']}"


def test_sli_producing_means_membership_of_a_monitor_based_slo():
    """The one relation with a mechanical definition, checked both ways. The
    dangerous drift is the quiet one: an archetype dropped from an SLO's
    membership while still claiming to produce its SLI."""
    producing = {aid for aid, a in POLICY["archetypes"].items()
                 if a["slo_relation"] == "sli_producing"}
    assert producing == MONITOR_SLO_MEMBERS


def test_no_classification_is_dead_vocabulary():
    used = {a["slo_relation"] for a in POLICY["archetypes"].values()}
    assert used == set(RELATIONS), set(RELATIONS) - used


def test_the_classification_separates_paging_from_explaining():
    """The reason §15 exists: `diagnostic` and `informational` monitors explain
    and record. If either can page, the classification is decoration."""
    for i in oc.expand_instances(POLICY):
        rel = POLICY["archetypes"][i["archetype"]]["slo_relation"]
        if rel in ("diagnostic", "informational"):
            assert not i["pages"], f"{i['key']} is {rel} and pages"


# =============================================================================
# C18 — SLO / catalog association integrity (§13)
# =============================================================================

def _findings(slos=None, services=None):
    return cr.slo_catalog_findings(POLICY, slos if slos is not None else SLOS,
                                   REGISTERED if services is None else services)


def _live(slo_id, **overrides):
    """A live SLO payload shaped like the Datadog API returns."""
    base = {
        "id": "slo900", "name": f"synthetic {slo_id}",
        "tags": [f"slo_id:{slo_id}", "env:prod", "service:identity-api",
                 "team:security", "owner:security", "managed_by:terraform"],
        "overall_status": [{}],
    }
    base.update(overrides)
    return base


def test_the_committed_estate_is_clean():
    """Every SLO in the fixture estate joins to a catalog entity, is owned, is
    production-scoped and is measurable. Anything below is a SEEDED defect."""
    assert _findings() == []


def test_an_orphan_slo_is_detected_but_does_not_block_a_deploy():
    """A promise nobody makes any more: the service was deleted, the SLO was
    not. It still reports, still green. Reported nightly; not the deploy's
    fault, so not the deploy's problem."""
    found = _findings(SLOS + [_live("slo-svc-deleted-service")])
    assert len(found) == 1
    assert "orphan" in found[0]["problem"]
    assert cr._blocks_deploy("C18", found[0]) is False


def test_a_duplicate_slo_id_is_detected():
    dupe = _live("slo-svc-identity-api", id="slo901", name="somebody made a copy")
    found = _findings(SLOS + [dupe])
    assert any("duplicate" in f["problem"] for f in found)


def test_an_slo_missing_from_the_estate_blocks_the_deploy():
    """The catalog promises it and Datadog does not have it — the apply that
    was supposed to create it did not."""
    remaining = [s for s in SLOS
                 if "slo_id:slo-svc-identity-api" not in s["tags"]]
    found = _findings(remaining)
    assert len(found) == 1
    assert found[0]["class"] == "declared_slo"
    assert cr._blocks_deploy("C18", found[0]) is True


def test_an_slo_owned_by_the_wrong_team_is_detected():
    broken = copy.deepcopy(SLOS)
    for s in broken:
        if "slo_id:slo-svc-identity-api" in s["tags"]:
            s["tags"] = [t for t in s["tags"] if not t.startswith(("team:", "owner:"))]
            s["tags"] += ["team:sre", "owner:sre"]
    found = _findings(broken)
    assert any("ownership" in f["problem"] for f in found)
    assert all(f["class"] == "declared_slo" for f in found)


def test_an_slo_scoped_outside_production_is_detected():
    broken = copy.deepcopy(SLOS)
    for s in broken:
        if "slo_id:slo-svc-identity-api" in s["tags"]:
            s["tags"] = [t if t != "env:prod" else "env:stage" for t in s["tags"]]
    assert any("env tag" in f["problem"] for f in _findings(broken))


def test_an_slo_associated_with_nothing_in_the_catalog_is_detected():
    broken = copy.deepcopy(SLOS)
    for s in broken:
        if "slo_id:slo-svc-identity-api" in s["tags"]:
            s["tags"] = [t if not t.startswith("service:") else "service:a-thing-that-left"
                         for t in s["tags"]]
    assert any("matches no catalog entity" in f["problem"] for f in _findings(broken))


def test_an_slo_that_is_green_only_because_no_data_arrives_is_detected():
    """The failure this check exists for. A 0/0 SLI cannot be violated, so
    silence reads as perfection — on the dashboard, in the review, and in the
    board pack."""
    broken = copy.deepcopy(SLOS)
    for s in broken:
        if "slo_id:slo-svc-identity-api" in s["tags"]:
            s["overall_status"] = [{"timeframe": "30d", "sli_value": None, "error": None}]
    found = _findings(broken)
    assert any("no SLI value" in f["problem"] for f in found)
    assert all(cr._blocks_deploy("C18", f) for f in found)


def test_absent_status_detail_is_not_read_as_missing_data():
    """`present and null` is the honest test. An absent key means the snapshot
    did not carry status detail — a property of the collection, not of the
    objective — and treating it as no-data would make the check cry wolf on
    every run."""
    assert _findings() == []


def test_a_monitor_slo_with_no_members_is_detected():
    services = {**REGISTERED, "orders-sql": SERVICES["orders-sql"]}
    live = SLOS + [_live("slo-svc-orders-sql", monitor_ids=[],
                         tags=["slo_id:slo-svc-orders-sql", "env:prod", "service:orders-sql",
                               "team:data-engineering", "owner:data-engineering"])]
    found = _findings(live, services)
    assert any("no members" in f["problem"] for f in found)


def test_an_unmeasurable_telemetry_dependency_is_reported_but_advisory():
    """settlement-batch's objectives read `acme.batch.*`, which nothing emits
    yet. That is the honest state — the objective exists and cannot be measured
    — and it is an estate note, not a reason to fail a deploy."""
    services = {**REGISTERED, "settlement-batch": SERVICES["settlement-batch"]}
    declared = sr.resolved_slos(POLICY, services)
    live = SLOS + [_live(sid, tags=[f"slo_id:{sid}", "env:prod",
                                    f"service:{s['service']}", f"team:{s['team']}",
                                    f"owner:{s['team']}"])
                   for sid, s in declared.items() if s["service"] == "settlement-batch"]
    found = _findings(live, services)
    assert found and all(f["class"] == "telemetry_dependency" for f in found)
    assert not any(cr._blocks_deploy("C18", f) for f in found)


def test_the_check_is_wired_into_the_report_and_both_gates():
    """A check nobody runs is a check that does not exist."""
    import build_inventory
    import profile_engine
    inv = {"resources": build_inventory.synthesize(300), "resource_count": 300}
    assignments = profile_engine.assign(inv, POLICY, REGISTERED)
    report = cr.run_checks(inv, assignments, [], SLOS + [_live("slo-svc-gone")], POLICY)
    assert report["summary"]["check_counts"]["C18"] == 1
    assert report["summary"]["deploy_blocking_counts"]["C18"] == 0
    assert "C18 SLO / catalog association integrity" in cr.to_markdown(report)


@pytest.mark.parametrize("slo_id", sorted(POLICY["slos"]))
def test_every_domain_slo_still_joins_to_the_estate(slo_id):
    """The domain catalog is the other half of §13: 20-odd objectives that must
    each exist in Datadog and belong to a real platform service."""
    tagged = [s for s in SLOS if f"slo_id:{slo_id}" in s["tags"]]
    assert len(tagged) == 1, slo_id


# --- scope vs profile: two keys, two questions -------------------------------
#
# These guard a defect that was live in the repository: `slo.profile` meant
# "which objective bundle" to the SLO resolver and "does this get its own SLO"
# to the entity resolver. Every registered entity used the second vocabulary,
# so the profile layer was unreachable — and because the resolver treated the
# mere PRESENCE of an `slo:` block as an opt-in, the four entities saying
# `domain` ("the domain SLO covers me") were each given the per-service SLO
# they were declining. Terraform built four; the coverage report counted one.

def test_declining_an_slo_does_not_materialize_one():
    """`scope: domain` is a service saying no. It must be read as no."""
    declining = {"name": "orders-sql", "team": "data-engineering", "tier": "tier1",
                 "service_archetype": "datastore", "slo": {"scope": "domain"}}
    assert not sr.materializes_per_service_slos(POLICY, declining)
    assert sr.resolved_slos(POLICY, {"orders-sql": declining}) == {}


def test_the_opt_in_is_the_scope_value_not_the_presence_of_a_block():
    base = {"name": "probe", "team": "sre", "tier": "tier1",
            "service_archetype": "api"}
    assert not sr.materializes_per_service_slos(POLICY, base)
    assert not sr.materializes_per_service_slos(POLICY, {**base, "slo": {"scope": "none"}})
    assert sr.materializes_per_service_slos(POLICY, {**base, "slo": {"scope": "per_service"}})


def test_a_tier0_entity_can_narrow_its_scope():
    """Narrowing has to work in both directions, or the catalog tag and the
    SLO that gets built disagree: the entity is tagged domain-scoped while a
    per-service SLO exists for it."""
    narrowed = {"name": "probe", "team": "sre", "tier": "tier0",
                "service_archetype": "api", "slo": {"scope": "domain"}}
    assert POLICY["tiers"]["tier0"]["slo"]["scope"] == "per_service"
    assert not sr.materializes_per_service_slos(POLICY, narrowed)


def test_the_entity_projection_carries_slo_through():
    """entity_as_service() feeds the SLO resolver. Dropping `slo` there did not
    fall back to a default — it made the opt-in and the profile layer dead."""
    ent = {"kind": "service", "name": "probe", "team": "sre", "criticality": "tier1",
           "service_archetype": "api", "slo": {"scope": "per_service",
                                               "profile": "api-standard"}}
    assert oc.entity_as_service(ent)["slo"] == ent["slo"]


def test_registered_entities_resolve_the_same_slos_the_coverage_report_counts():
    """End to end over the REAL registry, not a fixture: exactly the entities
    whose effective scope is per_service get an SLO, and no others."""
    import entity_resolver as er
    entities = oc.load_entities()
    services = oc.load_services()
    expected = {n for n, e in entities.items()
                if e.get("service_archetype") and er.resolve_slo_scope(e, POLICY) == "per_service"}
    got = {s["service"] for s in sr.resolved_slos(POLICY, services).values()}
    assert got == expected
