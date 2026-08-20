# OpenTelemetry Collector → Azure Container Apps

Deploys an OTel Collector **gateway** into an Azure **Container Apps
Environment (CAE)** with Bicep, from either Azure DevOps or GitHub Actions.
Apps in the environment send OTLP to it; it batches, samples, stamps resource
attributes and exports to Datadog.

Both pipelines are thin wrappers over the same `scripts/`, so a fix cannot land
in one CI system and silently miss the other.

```
deploy/otel-collector/
├── bicep/
│   ├── main.bicep              resource-group scoped orchestrator
│   ├── modules/
│   │   ├── environment.bicep   Log Analytics + CAE (+ optional managed agent)
│   │   ├── identity.bicep      user-assigned MI + AcrPull + KV Secrets User
│   │   └── collector.bicep     the collector Container App
│   └── params/{dev,qa,prod}.bicepparam
├── scripts/                    preflight · deploy · idempotency-gate · smoke
└── pipelines/azure-pipelines.yml
.github/workflows/otel-collector-{deploy,env}.yml
```

## Two ways to get telemetry out of a CAE

| | Managed OTel agent (built into the CAE) | Collector gateway (this) |
|---|---|---|
| Runs | inside the platform, no container | as a Container App you own |
| Control | fixed feature set | full: processors, sampling, redaction, multiple backends |
| API | **preview** only | stable |
| Secret handling | key inline in the environment resource | Key Vault reference resolved by managed identity |

This deploys the gateway. Setting `enableManagedOtelAgent: true` *additionally*
points the built-in agent at the gateway, so apps that are not instrumented
themselves still get their platform logs and metrics forwarded. That option
pins a preview API version on the environment resource — leave it off if your
organisation forbids preview APIs.

## Sending telemetry to it

The collector takes internal ingress on **4317 (OTLP/gRPC)** and **4318
(OTLP/HTTP)**. Point instrumented apps in the same environment at:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://ca-otel-collector-<env>:4317
```

Both endpoints are also returned as deployment outputs. Ingress is
**internal-only by design**: a collector reachable from the internet is an open
telemetry relay that anyone can inject spans and metrics into.

## How idempotency is enforced

ARM in incremental mode is idempotent *only if the template is*. Four things
break that, and each is a real failure mode:

| Anti-pattern | What it does | Handling |
|---|---|---|
| `utcNow()` / `newGuid()` defaults | new value every deployment → permanent drift | absent; the Validate stage greps the **compiled ARM** and fails if either reappears |
| Revision suffix from a build id | new Container Apps revision on every run, even with an identical image | suffix derives from the **image tag** alone |
| Literal secret values | write-only in ARM, so `what-if` reports a change forever and the gate can never go green | the API key is a **Key Vault reference**; the config resolves `${env:DD_API_KEY}` at runtime |
| System-assigned identity for ACR pull | identity does not exist until the app does → first deploy fails on image pull, second succeeds | **user-assigned** identity, created and granted first |

Then it is **verified**: after every apply the pipeline re-runs
`az deployment group what-if` and fails the build on any remaining
`Create`/`Delete`/`Modify`.

`Deploy` and `Unsupported` are reported but do not gate — ARM cannot diff those
resource types, and a permanently red gate is one people stop reading.

## Collector configuration

Built as a deterministic string in `collector.bicep` and passed via
`--config=env:OTEL_CONFIG`, so no volume mount or custom image is needed.

Pipeline order is deliberate:

```
memory_limiter → resource → probabilistic_sampler → batch → datadog
```

- **`memory_limiter` is first.** It can only shed load if it sees data before
  the batcher has buffered it. Behind `batch`, the collector is OOM-killed
  instead — and `GOMEMLIMIT` is set so Go's GC cooperates rather than fighting
  it.
- **`resource`** stamps the Tier 1 tags from `docs/tagging-standard.md`. Without
  them this platform's monitors evaluate against an empty set, which looks
  identical to healthy.
- **`probabilistic_sampler`** defaults to 100%. Lower it only with a stated
  reason: a sampled-away trace cannot be recovered later.
- **`batch` is last**, with a retry queue on the exporter so a Datadog blip
  does not drop telemetry.

Liveness and readiness probes hit the `health_check` extension on 13133, so a
collector that starts but cannot serve is replaced rather than left in rotation.

## Sizing

`minReplicas` is **≥ 1 in every environment, including dev** — a collector at
zero replicas silently drops the telemetry it exists to carry, and the gap is
indistinguishable from "the app sent nothing". Production runs 3 so a single
restart never blackholes a pipeline.

## Setup — Azure DevOps

1. **Service connection** — ARM connection named `sc-otel-collector` using
   **Workload Identity Federation**.
2. **Environments** — `otel-collector-dev`, `otel-collector-qa`,
   `otel-collector-prod`.
   - **Approvals** on prod.
   - An **Exclusive Lock** check on each. Azure DevOps has no `concurrency:`
     group; the lock plus `lockBehavior: sequential` (already in the YAML) is
     what stops two runs deploying to one resource group at once. Without the
     check, `lockBehavior` does nothing.
3. Create the pipeline from `pipelines/azure-pipelines.yml` and run it with a
   collector version and a target.

## Setup — GitHub Actions

1. **Entra app registration** with federated credentials for this repository,
   one per environment (`environment:otel-collector-prod`, …).
2. **Repository secrets**: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
   `AZURE_SUBSCRIPTION_ID`. No client secret — the workflow requests an OIDC
   token.
3. **Environments** `otel-collector-{dev,qa,prod}`, reviewers on prod.

## RBAC the deploying identity needs

| Scope | Role | Why |
|---|---|---|
| Resource group / subscription | `Contributor` | create the RG, CAE, collector, workspace |
| Key Vault | `User Access Administrator` *or* a pre-created assignment | the template grants `Key Vault Secrets User` to the collector identity |
| ACR (only if mirroring) | same | the template grants `AcrPull` |

If your org forbids `User Access Administrator` on pipeline identities, create
the role assignments out of band and set `acrName: ''` / pre-grant the vault.

## Prerequisites you must create first

- A **Key Vault** per environment holding the Datadog API key as a secret. The
  pipeline never sees the value — the collector reads it at runtime with its
  managed identity.
- Nothing else. The resource group, CAE, Log Analytics workspace, identity and
  collector are all created by the template.

## Promotion

`dev → qa → prod`, promoting the same immutable collector version. Production is
never promoted by a push in either system — it takes a deliberate run with
`target: prod`, behind the environment's approval. `latest` is rejected in
preflight.
