// =============================================================================
// OPENTELEMETRY COLLECTOR — deployed as a gateway Container App inside the CAE.
//
// Other container apps in the environment send OTLP to it over the internal
// ingress; it batches, limits memory, stamps resource attributes and exports
// to Datadog. Running a gateway rather than exporting straight from each app
// is what makes sampling, redaction and backend changes a one-place change.
//
// IDEMPOTENCY (each of these is a real defect, not a preference):
//   revisionSuffix   derives from the image tag alone. A build-id suffix mints
//                    a new revision on every run even when nothing changed.
//   the API key      is a Key Vault reference resolved by the app's managed
//                    identity, and the config references it as ${env:DD_API_KEY}
//                    at RUNTIME. A literal secret is write-only in ARM, so
//                    what-if would report a change forever.
//   the config       is a deterministic string built from parameters — no
//                    timestamps, no generated ids.
// =============================================================================

param appName string
param location string
param tags object
param environmentId string
param identityId string

@description('Collector image. Must be the CONTRIB distribution — the core image has no Datadog exporter.')
param image string = 'otel/opentelemetry-collector-contrib'

@description('Immutable image tag. Also drives the revision suffix.')
param imageTag string

param cpu string = '1.0'
param memory string = '2Gi'

@description('A collector must never scale to zero: at zero replicas the telemetry it was deployed to carry is silently dropped.')
@minValue(1)
param minReplicas int = 2
@minValue(1)
param maxReplicas int = 10

@description('Key Vault secret URL for the Datadog API key.')
param datadogApiKeyVaultUrl string

param datadogSite string = 'datadoghq.com'

// Resource attributes stamped onto every span, metric and log passing through.
// These are the Tier 1 tags from docs/tagging-standard.md: telemetry that does
// not carry them is invisible to this platform's monitors, which evaluate to no
// data and look identical to healthy.
param ddEnv string
param ddTeam string
param ddTier string
param ddAlertBand string
param collectorService string = 'otel-collector'
param appVersion string

@description('Percentage of traces to keep. 100 = keep everything.')
@minValue(1)
@maxValue(100)
param traceSamplePercentage int = 100

@description('Memory limit percentage at which the collector starts refusing data rather than being OOM-killed.')
@minValue(50)
@maxValue(95)
param memoryLimitPercentage int = 80

var grpcPort = 4317
var httpPort = 4318
var healthPort = 13133

// The collector configuration, assembled line by line so every interpolated
// value stays reviewable. `\${env:DD_API_KEY}` is ESCAPED: Bicep must emit it
// literally so the collector resolves it from the environment at runtime.
var configLines = [
  'receivers:'
  '  otlp:'
  '    protocols:'
  '      grpc:'
  '        endpoint: 0.0.0.0:${grpcPort}'
  '      http:'
  '        endpoint: 0.0.0.0:${httpPort}'
  ''
  'processors:'
  // memory_limiter MUST be first in every pipeline: it can only shed load if it
  // sees data before the batcher has buffered it.
  '  memory_limiter:'
  '    check_interval: 1s'
  '    limit_percentage: ${memoryLimitPercentage}'
  '    spike_limit_percentage: 25'
  '  resource:'
  '    attributes:'
  '      - key: deployment.environment'
  '        value: "${ddEnv}"'
  '        action: upsert'
  '      - key: team'
  '        value: "${ddTeam}"'
  '        action: upsert'
  '      - key: tier'
  '        value: "${ddTier}"'
  '        action: upsert'
  '      - key: alert_band'
  '        value: "${ddAlertBand}"'
  '        action: upsert'
  '      - key: service.version'
  '        value: "${appVersion}"'
  '        action: upsert'
  '  probabilistic_sampler:'
  '    sampling_percentage: ${traceSamplePercentage}'
  '  batch:'
  '    timeout: 10s'
  '    send_batch_size: 1000'
  '    send_batch_max_size: 2000'
  ''
  'extensions:'
  '  health_check:'
  '    endpoint: 0.0.0.0:${healthPort}'
  ''
  'exporters:'
  '  datadog:'
  '    api:'
  '      key: \${env:DD_API_KEY}'
  '      site: ${datadogSite}'
  '    retry_on_failure:'
  '      enabled: true'
  '      initial_interval: 5s'
  '      max_interval: 30s'
  '    sending_queue:'
  '      enabled: true'
  '      queue_size: 5000'
  ''
  'service:'
  '  extensions: [health_check]'
  '  telemetry:'
  '    logs:'
  '      level: info'
  '    metrics:'
  '      level: detailed'
  '  pipelines:'
  '    traces:'
  '      receivers: [otlp]'
  '      processors: [memory_limiter, resource, probabilistic_sampler, batch]'
  '      exporters: [datadog]'
  '    metrics:'
  '      receivers: [otlp]'
  '      processors: [memory_limiter, resource, batch]'
  '      exporters: [datadog]'
  '    logs:'
  '      receivers: [otlp]'
  '      processors: [memory_limiter, resource, batch]'
  '      exporters: [datadog]'
]
var collectorConfig = join(configLines, '\n')

var revisionSuffix = toLower(replace(replace(imageTag, '.', '-'), '_', '-'))

resource collector 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        {
          name: 'datadog-api-key'
          keyVaultUrl: datadogApiKeyVaultUrl
          identity: identityId
        }
      ]
      ingress: {
        // Internal only. A collector reachable from the internet is an open
        // telemetry relay: anyone can inject spans and metrics into the org.
        external: false
        targetPort: grpcPort
        transport: 'http2'   // OTLP/gRPC requires HTTP/2
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        // OTLP/HTTP alongside gRPC, for SDKs that only speak the HTTP protocol.
        additionalPortMappings: [
          {
            external: false
            targetPort: httpPort
            exposedPort: httpPort
          }
        ]
      }
    }
    template: {
      revisionSuffix: revisionSuffix
      containers: [
        {
          name: 'otel-collector'
          image: '${image}:${imageTag}'
          args: [
            '--config=env:OTEL_CONFIG'
          ]
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            { name: 'OTEL_CONFIG', value: collectorConfig }
            { name: 'DD_API_KEY', secretRef: 'datadog-api-key' }
            { name: 'DD_SITE', value: datadogSite }
            { name: 'DD_ENV', value: ddEnv }
            { name: 'DD_SERVICE', value: collectorService }
            { name: 'DD_VERSION', value: appVersion }
            // GOMEMLIMIT lets Go's GC cooperate with memory_limiter instead of
            // fighting it; without it the collector is OOM-killed before the
            // limiter ever sheds load.
            { name: 'GOMEMLIMIT', value: '${memoryLimitPercentage}MiB' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/', port: healthPort }
              initialDelaySeconds: 15
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/', port: healthPort }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'otlp-grpc-load'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

output appName string = collector.name
output appId string = collector.id
output latestRevision string = collector.properties.latestRevisionName
// The in-environment address other container apps send OTLP to.
output otlpGrpcEndpoint string = 'http://${collector.name}:${grpcPort}'
output otlpHttpEndpoint string = 'http://${collector.name}:${httpPort}'
