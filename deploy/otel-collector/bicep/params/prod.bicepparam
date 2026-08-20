using '../main.bicep'

param environmentSuffix = 'prod'
param imageTag = readEnvironmentVariable('IMAGE_TAG')
param appVersion = readEnvironmentVariable('APP_VERSION')
param gitCommitSha = readEnvironmentVariable('GIT_COMMIT_SHA', '')
param gitRepositoryUrl = readEnvironmentVariable('GIT_REPOSITORY_URL', '')

param acrLoginServer = readEnvironmentVariable('ACR_LOGIN_SERVER', '')
param acrName = readEnvironmentVariable('ACR_NAME', '')
param keyVaultName = readEnvironmentVariable('KEY_VAULT_NAME')
param datadogApiKeyVaultUrl = readEnvironmentVariable('DD_API_KEY_VAULT_URL')

param team = 'observability-platform'
param tier = 'tier1'
param alertBand = 'critical'

// Two replicas minimum so a single restart never blackholes telemetry, and
// headroom to absorb a deploy storm without the memory limiter shedding data.
param cpu = '2.0'
param memory = '4Gi'
param minReplicas = 3
param maxReplicas = 20
param logRetentionInDays = 90

// Head sampling at the gateway. 100 keeps everything; lower it only with a
// stated reason, because a sampled-away trace cannot be recovered later.
param traceSamplePercentage = 100
param memoryLimitPercentage = 80
