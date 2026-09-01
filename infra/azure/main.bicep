targetScope = 'resourceGroup'
param location string = resourceGroup().location
param suffix string = uniqueString(resourceGroup().id)
param tags object = { workload: 'autonomous-order-to-cash-revenue-assurance', evidence: 'deployment-contract' }
resource events 'Microsoft.EventHub/namespaces@2024-01-01' = { name: 'evhns-o2c-${suffix}', location: location, tags: tags, sku: { name: 'Standard', tier: 'Standard', capacity: 1 }, properties: { publicNetworkAccess: 'Enabled', minimumTlsVersion: '1.2' } }
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = { name: 'law-o2c-${suffix}', location: location, tags: tags, properties: { retentionInDays: 30 } }
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = { name: 'kv-o2c-${suffix}', location: location, tags: tags, properties: { tenantId: subscription().tenantId, sku: { family: 'A', name: 'standard' }, enableRbacAuthorization: true, enableSoftDelete: true, softDeleteRetentionInDays: 90, publicNetworkAccess: 'Enabled' } }
output eventHubNamespaceId string = events.id
output workspaceId string = logs.id
output keyVaultId string = vault.id

