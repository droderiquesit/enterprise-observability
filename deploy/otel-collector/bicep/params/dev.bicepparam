using '../main.bicep'

// IMAGE_TAG and APP_VERSION are injected by the pipeline; everything else stays
// reviewable in git, and both CI systems pass exactly the same values.
param environmentSuffix = 'dev'
param imageTag = readEnvironmentVariable('IMAGE_TAG')
param appVersion = readEnvironmentVariable('APP_VERSION')
param gitCommitSha = readEnvironmentVariable('GIT_COMMIT_SHA', '')
param gitRepositoryUrl = readEnvironmentVariable('GIT_REPOSITORY_URL', '')

param acrLoginServer = readEnvironmentVariable('ACR_LOGIN_SERVER', '')
param acrName = readEnvironmentVariable('ACR_NAME', '')
param keyVaultName = readEnvironmentVariable('KEY_VAULT_NAME')
param datadogApiKeyVaultUrl = readEnvironmentVariable('DD_API_KEY_VAULT_URL')

param team = 'observability-platform'
param tier = 'tier3'
param alertBand = 'baseline'

// Smallest viable gateway. minReplicas is 1 rather than 0 even in dev: a
// collector at zero replicas drops the telemetry it exists to carry, and the
// gap looks identical to "the app sent nothing".
param cpu = '0.5'
param memory = '1Gi'
param minReplicas = 1
param maxReplicas = 3
param traceSamplePercentage = 100
param logRetentionInDays = 30
