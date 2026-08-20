using '../main.bicep'

param environmentSuffix = 'qa'
param imageTag = readEnvironmentVariable('IMAGE_TAG')
param appVersion = readEnvironmentVariable('APP_VERSION')
param gitCommitSha = readEnvironmentVariable('GIT_COMMIT_SHA', '')
param gitRepositoryUrl = readEnvironmentVariable('GIT_REPOSITORY_URL', '')

param acrLoginServer = readEnvironmentVariable('ACR_LOGIN_SERVER', '')
param acrName = readEnvironmentVariable('ACR_NAME', '')
param keyVaultName = readEnvironmentVariable('KEY_VAULT_NAME')
param datadogApiKeyVaultUrl = readEnvironmentVariable('DD_API_KEY_VAULT_URL')

param team = 'observability-platform'
param tier = 'tier2'
param alertBand = 'standard'

param cpu = '1.0'
param memory = '2Gi'
param minReplicas = 2
param maxReplicas = 6
param traceSamplePercentage = 100
