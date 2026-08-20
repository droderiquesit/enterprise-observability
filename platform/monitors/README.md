# Self-service monitors

A team drops **one YAML file** here to add a monitor the catalog does not
already provide, or to override how a catalog archetype behaves for one
service. Everything else — naming, tags, thresholds, routing, runbook,
on-call, recovery, ServiceNow behaviour — is derived by the platform.

The directory is intentionally **empty of examples**. A file here is deployed;
an example that is deployed is an artificial monitor in production. The worked
reference manifest lives at `tests/fixtures/self_service_example.yaml`, where
the self-service test suite validates it on every pull request.

## Adding one

1. Copy `tests/fixtures/self_service_example.yaml` here and rename it — the
   filename must match `monitor.name`.
2. Point it at a service registered in `platform/services/`.
3. If it re-uses a catalog archetype that already covers the service, write a
   `justification`. The validator refuses a near-duplicate without one.
4. Open a pull request. `validate_monitors.py` explains anything wrong before
   Terraform runs.
