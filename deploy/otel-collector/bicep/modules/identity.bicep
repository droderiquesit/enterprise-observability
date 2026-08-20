// =============================================================================
// USER-ASSIGNED MANAGED IDENTITY + the two role assignments it needs.
//
// A user-assigned identity rather than system-assigned, deliberately: the ACR
// pull grant must exist BEFORE the container app first starts, and a
// system-assigned identity does not exist until the app is created — which
// makes the first deployment fail on image pull and the second succeed. That
// is the definition of non-idempotent.
// =============================================================================

param identityName string
param location string
param tags object

@description('Name of the Azure Container Registry to grant AcrPull on. Empty = skip.')
param acrName string = ''

@description('Name of the Key Vault to grant secret read on. Empty = skip.')
param keyVaultName string = ''

// Built-in Azure role definition ids. These are PUBLIC, documented, globally
// constant GUIDs — the same values in every tenant — not credentials:
//   https://learn.microsoft.com/azure/role-based-access-control/built-in-roles
//
// The `gitleaks:allow` markers are deliberate and narrow. A secret scanner's
// generic-entropy rule cannot distinguish a published role id from an API key,
// and it flagged the second of these on entropy alone. Suppressing the two
// specific lines keeps the scan meaningful everywhere else; a repository-wide
// allowlist for high-entropy strings would not.
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // gitleaks:allow AcrPull
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6' // gitleaks:allow Key Vault Secrets User

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = if (!empty(acrName)) {
  name: acrName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = if (!empty(keyVaultName)) {
  name: keyVaultName
}

// guid() over (scope, principal, role) is deterministic: the same inputs always
// produce the same assignment name, so re-running is a no-op instead of a
// "RoleAssignmentExists" failure.
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acrName)) {
  name: guid(acr.id, identity.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(keyVaultName)) {
  name: guid(keyVault.id, identity.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output identityId string = identity.id
output principalId string = identity.properties.principalId
output clientId string = identity.properties.clientId
