"""The entity model: a thing is catalogued as what it IS.

The defect this suite exists to prevent is one line of the audit (§5): *every
catalog object is a Service*. A database, a Service Bus topic and a VM all
arrived in the Software Catalog as services, which makes ownership, dependency
maps and entity scorecards wrong at the source.

Four properties are protected:
  1. A datastore does not become a Service — nor does a queue, nor a system.
  2. A VM stays infrastructure. It is not a catalog entity at all, and saying
     otherwise is an error rather than a quietly-created Service.
  3. Every committed entity file validates against the schema.
  4. Kind inference is deterministic — same input, same kind, every time, with
     no dependence on file order or on which fields happen to be present.
"""
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

import entity_resolver as er
import obs_common as oc
import validate_policy as vp

POLICY = oc.load_policy()
ENTITIES = oc.load_entities()
SCHEMA = json.loads((oc.PLATFORM_DIR / "schemas" / "entity.schema.json").read_text())
ENTITY_DIR = oc.PLATFORM_DIR / "entities"


def _entity(**overrides):
    """A minimal valid entity, mutated. Used for the negative cases, which must
    never be committed files — an example in platform/entities/ is APPLIED."""
    base = {
        "kind": "service",
        "name": "example-service",
        "team": "sre",
        "criticality": "tier2",
        "service_archetype": "api",
        "description": "A service used only by this test suite.",
        "envs": ["prod"],
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


# --- 3. every entity file validates ------------------------------------------

def test_every_entity_file_validates_against_the_schema():
    files = sorted(ENTITY_DIR.glob("*.yaml"))
    assert files, "the entity registry is empty — nothing is being catalogued"
    for path in files:
        jsonschema.validate(yaml.safe_load(path.read_text()), SCHEMA)


@pytest.mark.parametrize("bad,why", [
    (_entity(kind="vm"), "a kind outside the vocabulary"),
    (_entity(service_archetype=None), "a service with no archetype to select packs"),
    (_entity(kind="system", service_archetype=None), "a system with no components"),
    (_entity(kind="datastore", service_archetype="datastore",
             dependencies=["identity-api"]), "dependsOn on a kind whose spec lacks it"),
    (_entity(kind="repository", service_archetype=None), "a repository with no URL"),
    (_entity(criticality="tier9"), "a criticality outside the tier vocabulary"),
    (_entity(components=["service:x"]), "components on something that is not a system"),
    (_entity(name="Orders_SQL"), "a name that cannot match a telemetry tag"),
])
def test_the_schema_rejects_a_malformed_entity(bad, why):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"entity": bad}, SCHEMA)


def test_every_entity_file_is_named_after_its_entity():
    for path in sorted(ENTITY_DIR.glob("*.yaml")):
        assert yaml.safe_load(path.read_text())["entity"]["name"] == path.stem


def test_the_migrated_services_kept_every_field():
    """platform/services/ → platform/entities/ was a rename, not a redesign.

    The expected values are written out here rather than read from the old
    files, because the old files are gone: this test is the record that the
    migration was lossless.
    """
    expected = {
        "identity-api": {
            "team": "security", "criticality": "tier0", "service_archetype": "api",
            "description": "Enterprise authentication and token issuance.",
            "envs": ["dev", "qa", "stage", "prod"],
            "dependencies": ["entra-id", "sessions-redis"],
            "repo": "https://github.com/acme/identity-api",
        },
        "order-events-consumer": {
            "team": "application-development", "criticality": "tier1",
            "service_archetype": "event_consumer",
            "description": "Consumes order lifecycle events and updates downstream systems.",
            "envs": ["dev", "qa", "stage", "prod"],
            "dependencies": ["orders-topic", "orders-sql"],
            "repo": "https://github.com/acme/order-events-consumer",
        },
        "reporting-portal": {
            "team": "application-development", "criticality": "tier2",
            "service_archetype": "web",
            "description": "Internal reporting and analytics portal.",
            "envs": ["dev", "qa", "stage", "prod"],
            "dependencies": ["warehouse", "identity-api"],
            "repo": "https://github.com/acme/reporting-portal",
        },
    }
    for name, want in expected.items():
        got = ENTITIES[name]
        repo = want.pop("repo")
        for field, value in want.items():
            assert got[field] == value, f"{name}.{field}"
        assert any(link["url"] == repo for link in got["links"]), name


def test_a_registration_is_never_written_twice():
    """A name in both registries is two Terraform resources writing one Datadog
    entity. platform/services/ ships empty for exactly this reason."""
    legacy = {oc._yaml(f)["service"]["name"]
              for f in (oc.PLATFORM_DIR / "services").glob("*.yaml")}
    assert legacy & set(ENTITIES) == set()


def test_the_legacy_service_format_still_loads():
    """Superseded is not removed: obs_common.load_services() still merges both
    registries, so every existing consumer reads what it always read."""
    services = oc.load_services()
    assert services["identity-api"]["tier"] == "tier0"
    assert services["identity-api"]["team"] == "security"
    # Kinds that have no packs are not service-shaped and must not appear.
    assert "order-management" not in services
    assert "orders-topic" not in services


# --- 1. a datastore does not become a Service --------------------------------

@pytest.mark.parametrize("name,kind,datadog_kind", [
    ("orders-sql", "datastore", "datastore"),
    ("orders-topic", "queue", "queue"),
    ("order-management", "system", "system"),
    ("identity-api", "service", "service"),
    ("reporting-portal", "frontend_app", "service"),
])
def test_each_entity_resolves_to_its_own_kind(name, kind, datadog_kind):
    resolved = er.resolve(ENTITIES[name], POLICY, ENTITIES)
    assert resolved["kind"] == kind
    assert resolved["datadog_kind"] == datadog_kind


def test_a_datastore_is_not_emitted_as_a_service():
    doc = er.entity_document(er.resolve(ENTITIES["orders-sql"], POLICY, ENTITIES))
    assert doc["kind"] == "datastore"
    assert doc["apiVersion"] == "v3"
    # A datastore's telemetry is keyed by db_instance, not by `service`, so it
    # must not claim service-tagged performance data or carry a `service:` tag.
    assert "datadog" not in doc
    assert not any(t.startswith("service:") for t in doc["metadata"]["tags"])


def test_a_queue_is_not_the_service_that_consumes_it():
    """The distinction the service-only model could not express."""
    assert er.resolve(ENTITIES["orders-topic"], POLICY, ENTITIES)["kind"] == "queue"
    consumer = er.resolve(ENTITIES["order-events-consumer"], POLICY, ENTITIES)
    assert consumer["kind"] == "service"
    assert "queue:orders-topic" in consumer["depends_on"]


def test_every_emitted_kind_is_one_datadog_actually_accepts():
    """The provider validates `apiVersion` and nothing else, so an unsupported
    kind is an APPLY-time failure against the live org. This is the check that
    moves it to the pull request."""
    accepted = POLICY["entity_kinds_doc"]["datadog_entity_kinds"]
    for name, ent in ENTITIES.items():
        resolved = er.resolve(ent, POLICY, ENTITIES)
        if resolved["emits"]:
            assert resolved["datadog_kind"] in accepted, name


def test_frontend_app_is_emitted_as_a_service_and_says_so():
    """The v3 entity union has no UI kind. The compromise is only acceptable
    while it is visible: `spec.type: web` plus an `entity_kind:` tag."""
    doc = er.entity_document(er.resolve(ENTITIES["reporting-portal"], POLICY, ENTITIES))
    assert doc["kind"] == "service"
    assert doc["spec"]["type"] == "web"
    assert "entity_kind:frontend_app" in doc["metadata"]["tags"]


def test_a_repository_produces_no_datadog_entity():
    """Datadog has no repository kind. Declaring one is legal and emits
    nothing — with a recorded reason, so "nothing was created" is a decision
    rather than an apparent omission."""
    resolved = er.resolve(
        _entity(kind="repository", name="identity-api-repo", service_archetype=None,
                repository_url="https://github.com/acme/identity-api",
                owns=["identity-api"]),
        POLICY, ENTITIES)
    assert resolved["emits"] is False
    assert resolved["datadog_kind"] is None
    assert "no repository entity kind" in resolved["not_emitted_reason"]


# --- 2. a VM stays infrastructure --------------------------------------------

def test_an_infrastructure_resource_has_no_entity_kind():
    """A VM is a host in Datadog's infrastructure list, monitored by the
    host-core pack through tags. It is not a catalog entity."""
    vm = _entity(name="vm-app-eastus2-014", kind=None,
                 service_archetype="infrastructure_resource",
                 description="Application VM in East US 2, part of the app fleet.")
    assert er.infer_kind(vm, POLICY) is None
    resolved = er.resolve(vm, POLICY, ENTITIES)
    assert resolved["emits"] is False
    assert "infrastructure list" in resolved["not_emitted_reason"]


def test_calling_a_vm_a_service_is_rejected():
    """The failure mode being prevented: someone declares `kind: service` on a
    VM and the catalog gains a Service that is really a host."""
    vm = _entity(name="vm-app-eastus2-014", kind="service",
                 service_archetype="infrastructure_resource",
                 description="Application VM in East US 2, part of the app fleet.")
    errs = er.validate(vm, POLICY, ENTITIES)
    assert any("is not a catalog entity" in e for e in errs), errs


def test_a_datastore_declared_as_a_service_is_rejected():
    ent = _entity(name="orders-sql-copy", kind="service", service_archetype="datastore",
                  description="An Azure SQL database mis-declared as a service.")
    assert any("implies kind 'datastore'" in e for e in er.validate(ent, POLICY, ENTITIES))


def test_no_registered_entity_is_infrastructure():
    for name, ent in ENTITIES.items():
        assert er.infer_kind(ent, POLICY) is not None, name


# --- 4. kind inference is deterministic --------------------------------------

def test_kind_inference_is_total_over_the_archetype_vocabulary():
    """Every service_archetype maps, so inference never falls through to a
    guess. `null` is a real answer (infrastructure), not a missing one."""
    vocab = set(POLICY["global"]["tag_vocabulary"]["service_archetype"])
    mapping = POLICY["entity_kinds_doc"]["kind_by_service_archetype"]
    assert set(mapping) == vocab
    kinds = set(POLICY["entity_kinds"])
    for sa, kind in mapping.items():
        assert kind is None or kind in kinds, sa


def test_kind_inference_is_stable_and_order_independent():
    for name, ent in ENTITIES.items():
        first = er.infer_kind(ent, POLICY)
        assert all(er.infer_kind(ent, POLICY) == first for _ in range(3)), name
    shuffled = dict(reversed(list(ENTITIES.items())))
    assert ({n: er.resolve(e, POLICY, ENTITIES) for n, e in ENTITIES.items()}
            == {n: er.resolve(e, POLICY, shuffled) for n, e in shuffled.items()})


def test_a_declared_kind_never_depends_on_the_archetype():
    """`kind:` is the declaration; the archetype only fills the gap when it is
    absent. A queue has no archetype at all and still resolves."""
    assert "service_archetype" not in ENTITIES["orders-topic"]
    assert er.infer_kind(ENTITIES["orders-topic"], POLICY) == "queue"


def test_the_document_is_byte_stable():
    """Tags are sorted and references are sorted, so a no-op re-plan is a
    no-op — a catalog that churns on every apply is a catalog nobody reads."""
    for name, ent in ENTITIES.items():
        doc = er.entity_document(er.resolve(ent, POLICY, ENTITIES))
        assert doc["metadata"]["tags"] == sorted(doc["metadata"]["tags"]), name
        for key in ("dependsOn", "components", "componentOf"):
            assert doc["spec"].get(key, []) == sorted(doc["spec"].get(key, [])), name


# --- references, systems, ownership ------------------------------------------

def test_a_bare_dependency_is_typed_from_the_registry():
    """`orders-sql` is written bare and resolves to `datastore:orders-sql`;
    a name outside the catalog resolves to `service:` and stays there."""
    assert er.entity_ref("orders-sql", ENTITIES, POLICY) == "datastore:orders-sql"
    assert er.entity_ref("entra-id", ENTITIES, POLICY) == "service:entra-id"
    assert er.entity_ref("queue:orders-topic", ENTITIES, POLICY) == "queue:orders-topic"


def test_system_membership_is_declared_once_and_derived_backwards():
    system = er.resolve(ENTITIES["order-management"], POLICY, ENTITIES)
    assert system["components"] == [
        "datastore:orders-sql", "queue:orders-topic", "service:order-events-consumer"]
    for member in ("orders-sql", "orders-topic", "order-events-consumer"):
        # componentOf appears on the member without the member declaring it.
        assert "system" not in ENTITIES[member]
        assert er.resolve(ENTITIES[member], POLICY, ENTITIES)["component_of"] \
            == ["system:order-management"]


def test_a_system_cannot_contain_something_the_catalog_does_not_know():
    ghost = _entity(kind="system", name="ghost-system", service_archetype=None,
                    components=["service:does-not-exist"],
                    description="A system naming a component that is not registered.")
    assert any("not a registered entity" in e
               for e in er.validate(ghost, POLICY, ENTITIES))


def test_a_kind_without_depends_on_never_emits_dependencies():
    """EntityV3DatastoreSpec has componentOf/lifecycle/tier/type and nothing
    else, so a dependency written on a datastore would be discarded by the API.
    It is rejected, and the resolver refuses to emit it either way."""
    ent = dict(ENTITIES["orders-sql"], dependencies=["identity-api"])
    assert er.resolve_dependencies(ent, ENTITIES, POLICY) == []
    assert any("silently discarded" in e for e in er.validate(ent, POLICY, ENTITIES))


def test_the_oncall_carrier_is_visible_when_it_is_not_the_owner():
    doc = er.entity_document(er.resolve(ENTITIES["orders-sql"], POLICY, ENTITIES))
    assert doc["metadata"]["owner"] == "data-engineering"
    assert doc["metadata"]["contacts"][0]["type"] == "email"


def test_every_entity_carries_the_owner_applied_tag_contract():
    """docs/tagging-standard.md: env, team, tier, service_archetype, alert_band
    (and `service` where the telemetry is keyed by it). The catalog entity
    carries the same facets the monitors select on, so the two can be joined."""
    for name, ent in ENTITIES.items():
        tags = dict(t.split(":", 1) for t in er.resolve_tags(ent, POLICY))
        for required in ("env", "team", "tier", "alert_band", "entity_kind",
                         "domain", "managed_by"):
            assert required in tags, f"{name} is missing {required}"
        assert tags["managed_by"] == "terraform"


def test_derived_values_agree_with_the_tier_policy():
    for name, ent in ENTITIES.items():
        tier = POLICY["tiers"][ent["criticality"]]
        assert er.resolve_monitoring_profile(ent, POLICY) == tier["monitoring_profile"]
        assert er.resolve_slo_profile(ent, POLICY) in POLICY["entity_kinds_doc"]["slo_profiles"]


# --- the gate ----------------------------------------------------------------

def test_the_policy_lint_accepts_every_committed_entity():
    assert [e for e in vp.lint() if e.startswith("[ENTITY]")] == []


def test_the_census_counts_what_was_actually_built():
    census = er.census(POLICY, ENTITIES)
    assert census["total"] == len(ENTITIES)
    # The §5 evidence in one assertion: the catalog is no longer all services.
    assert set(census["by_datadog_kind"]) >= {"service", "datastore", "queue", "system"}
    assert census["by_datadog_kind"]["service"] < census["total"]


def test_the_module_and_the_resolver_read_the_same_policy_file():
    """HCL and Python must not each carry their own copy of the kind rules."""
    stack = (Path(__file__).resolve().parent.parent / "stacks" / "foundation" /
             "main.tf").read_text()
    assert "policy/entity_kinds.yaml" in stack
    assert "modules/catalog_entity" in stack
