// =============================================================================
// CONTAINER APPS ENVIRONMENT (CAE) + its Log Analytics workspace.
//
// Split into its own module because the environment has a different lifecycle
// from the app: it is created once and then shared, while the app is
// redeployed on every release. Keeping them together would mean every app
// deployment carried the authority to change the environment.
// =============================================================================

@description('Name of the Container Apps Environment.')
param environmentName string

@description('Name of the Log Analytics workspace backing the environment.')
param logAnalyticsName string

param location string
param tags object

@description('Log retention. 30 days is the free tier; raise deliberately, it is billable.')
@minValue(30)
@maxValue(730)
param retentionInDays int = 30

@description('Deploy the environment as internal-only (no public ingress possible).')
param internalOnly bool = false

@description('Existing subnet resource id for VNet integration. Empty = no VNet integration.')
param infrastructureSubnetId string = ''

@description('Zone redundancy. Requires a VNet-integrated environment.')
param zoneRedundant bool = false

@description('''
Also configure the CAE's BUILT-IN managed OpenTelemetry agent to forward the
platform's own app logs/traces/metrics to the collector deployed by this stack.

This is a separate mechanism from the collector: the managed agent runs inside
the environment and needs no container. It is worth enabling because it
captures telemetry from apps that are not themselves instrumented.

It is a PREVIEW feature, which is why this resource pins a preview API version.
Leave it off if your organisation forbids preview APIs.
''')
param enableManagedOtelAgent bool = false

@description('OTLP endpoint the managed agent forwards to — normally the collector this stack deploys.')
param managedAgentOtlpEndpoint string = ''

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

// 2024-10-02-preview rather than a stable version, solely because
// `openTelemetryConfiguration` (the managed agent) exists only in preview. The
// rest of the resource is identical across both.
resource environment 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        // listKeys() is resolved by ARM at deployment time and never appears in
        // the compiled template, the parameter file, or a pipeline log.
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    zoneRedundant: zoneRedundant
    vnetConfiguration: empty(infrastructureSubnetId) ? null : {
      internal: internalOnly
      infrastructureSubnetId: infrastructureSubnetId
    }
    openTelemetryConfiguration: (enableManagedOtelAgent && !empty(managedAgentOtlpEndpoint)) ? {
      destinationsConfiguration: {
        otlpConfigurations: [
          {
            name: 'gateway'
            endpoint: managedAgentOtlpEndpoint
            // Inside the environment; traffic never leaves the CAE's network.
            insecure: true
          }
        ]
      }
      tracesConfiguration: { destinations: ['gateway'] }
      logsConfiguration: { destinations: ['gateway'] }
      metricsConfiguration: { destinations: ['gateway'] }
    } : null
  }
}

output environmentId string = environment.id
output environmentName string = environment.name
output defaultDomain string = environment.properties.defaultDomain
output logAnalyticsId string = logAnalytics.id
