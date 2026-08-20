// =============================================================================
// OPENTELEMETRY COLLECTOR → AZURE CONTAINER APPS ENVIRONMENT (CAE)
//
// Deploys a collector GATEWAY into a Container Apps Environment. Apps in the
// environment send OTLP to it; it batches, samples, stamps resource attributes
// and exports to Datadog. One deployment produces the whole stack, and running
// it twice with the same inputs changes nothing — a property the pipeline
// asserts with a post-apply `what-if` rather than assuming.
//
//   main.bicep
//     ├── modules/environment.bicep  Log Analytics + CAE (+ optional managed
//     │                              OTel agent, forwarding to the collector)
//     ├── modules/identity.bicep     user-assigned MI + AcrPull + KV Secrets User
//     └── modules/collector.bicep    the collector Container App
//
// Two ways to get telemetry OUT of a CAE, and this deploys the first while
// optionally wiring the second into it:
//   1. this collector — full control over processors, sampling and backends;
//   2. the CAE's built-in managed OTel agent — no container, but a fixed
//      feature set. Set `enableManagedOtelAgent` and it forwards to (1).
// =============================================================================

targetScope = 'resourceGroup'

@description('Workload name. Drives every resource name, so keep it stable.')
@minLength(3)
@maxLength(24)
param workloadName string = 'otel-collector'

@allowed(['dev', 'qa', 'stage', 'prod'])
param environmentSuffix string

param location string = resourceGroup().location

// --- environment (CAE) -------------------------------------------------------
@description('Create the CAE here, or attach the collector to an existing one.')
param createEnvironment bool = true

@description('Resource id of a pre-existing CAE. Required when createEnvironment is false.')
param existingEnvironmentId string = ''

param logRetentionInDays int = 30
param environmentInternalOnly bool = false
param infrastructureSubnetId string = ''
param zoneRedundant bool = false

@description('Also point the CAE built-in managed OTel agent at this collector (preview feature).')
param enableManagedOtelAgent bool = false

// --- collector image ---------------------------------------------------------
@description('Collector image. MUST be the contrib distribution — core has no Datadog exporter.')
param image string = 'otel/opentelemetry-collector-contrib'

@description('Immutable image tag. NEVER `latest`: it makes the deployment unreproducible and defeats revision tracking.')
param imageTag string

@description('ACR login server, if mirroring the image privately. Empty = pull from Docker Hub.')
param acrLoginServer string = ''

@description('ACR name for the AcrPull grant. Empty to skip.')
param acrName string = ''

// --- runtime -----------------------------------------------------------------
param cpu string = '1.0'
param memory string = '2Gi'
@minValue(1)
param minReplicas int = 2
@minValue(1)
param maxReplicas int = 10
param traceSamplePercentage int = 100
param memoryLimitPercentage int = 80

// --- secrets -----------------------------------------------------------------
@description('Key Vault holding the Datadog API key.')
param keyVaultName string

@description('Key Vault secret URL for the Datadog API key. The value never enters the template.')
param datadogApiKeyVaultUrl string

param datadogSite string = 'datadoghq.com'

// --- observability contract (docs/tagging-standard.md, Tier 1) ---------------
@description('Owning team handle from platform/policy/teams.yaml.')
param team string

@allowed(['tier0', 'tier1', 'tier2', 'tier3'])
param tier string

@allowed(['none', 'baseline', 'standard', 'critical'])
param alertBand string

@description('Deployment version from the pipeline — monotonic, and it carries the commit.')
param appVersion string

param gitCommitSha string = ''
param gitRepositoryUrl string = ''

@description('Extra Azure resource tags, merged over the standard set.')
param additionalTags object = {}

// --- naming ------------------------------------------------------------------
var suffix = '${workloadName}-${environmentSuffix}'
var names = {
  environment: 'cae-${suffix}'
  logAnalytics: 'log-${suffix}'
  identity: 'id-${suffix}'
  collector: 'ca-${suffix}'
}

// A collector is infrastructure for every other service, so it is tagged as
// `platform_service` regardless of what it carries.
var standardTags = union({
  env: environmentSuffix
  service: workloadName
  team: team
  tier: tier
  service_archetype: 'platform_service'
  alert_band: alertBand
  managed_by: 'bicep'
  version: appVersion
  git_commit_sha: gitCommitSha
  git_repository_url: gitRepositoryUrl
}, additionalTags)

// The address the collector will occupy. Known before deployment because the
// name is deterministic — which is what lets the environment's managed agent be
// pointed at the collector in the SAME deployment, rather than needing a second
// pass after the collector exists.
var collectorOtlpEndpoint = 'http://${names.collector}:4317'

// --- deployment --------------------------------------------------------------
module environment 'modules/environment.bicep' = if (createEnvironment) {
  name: 'cae-${environmentSuffix}'
  params: {
    environmentName: names.environment
    logAnalyticsName: names.logAnalytics
    location: location
    tags: standardTags
    retentionInDays: logRetentionInDays
    internalOnly: environmentInternalOnly
    infrastructureSubnetId: infrastructureSubnetId
    zoneRedundant: zoneRedundant
    enableManagedOtelAgent: enableManagedOtelAgent
    managedAgentOtlpEndpoint: collectorOtlpEndpoint
  }
}

module identity 'modules/identity.bicep' = {
  name: 'identity-${environmentSuffix}'
  params: {
    identityName: names.identity
    location: location
    tags: standardTags
    acrName: acrName
    keyVaultName: keyVaultName
  }
}

module collector 'modules/collector.bicep' = {
  name: 'collector-${environmentSuffix}'
  params: {
    appName: names.collector
    location: location
    tags: standardTags
    environmentId: createEnvironment ? environment!.outputs.environmentId : existingEnvironmentId
    identityId: identity.outputs.identityId
    image: empty(acrLoginServer) ? image : '${acrLoginServer}/${image}'
    imageTag: imageTag
    cpu: cpu
    memory: memory
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    traceSamplePercentage: traceSamplePercentage
    memoryLimitPercentage: memoryLimitPercentage
    datadogApiKeyVaultUrl: datadogApiKeyVaultUrl
    datadogSite: datadogSite
    ddEnv: environmentSuffix
    ddTeam: team
    ddTier: tier
    ddAlertBand: alertBand
    collectorService: workloadName
    appVersion: appVersion
  }
}

output collectorName string = collector.outputs.appName
output collectorId string = collector.outputs.appId
output latestRevision string = collector.outputs.latestRevision
@description('Point instrumented apps at this. OTEL_EXPORTER_OTLP_ENDPOINT.')
output otlpGrpcEndpoint string = collector.outputs.otlpGrpcEndpoint
output otlpHttpEndpoint string = collector.outputs.otlpHttpEndpoint
output environmentId string = createEnvironment ? environment!.outputs.environmentId : existingEnvironmentId
output identityPrincipalId string = identity.outputs.principalId
