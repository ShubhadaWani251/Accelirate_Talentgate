// =============================================================================
// Per-project pattern: one staging + one production web app (on the shared
// plans) and one staging + one production database (on the shared servers).
// Every app gets a system-assigned identity, HTTPS-only, TLS 1.2, Always On,
// a /health probe, HTTP/2, FTPS disabled, and VNet integration.
// =============================================================================

@description('Project short name (lowercase). Used for app + database names.')
param projectName string

param location string
param tags object

@description('Suffix appended to globally-unique web app names.')
param nameSuffix string

param linuxFxVersion string
param prodPlanId string
param stagingPlanId string
param prodAppsSubnetId string
param stagingAppsSubnetId string
param prodPgServerName string
param stagingPgServerName string
param storageAccountName string
param assignStorageRbac bool

var project = toLower(projectName)

// Storage Blob Data Contributor
var blobContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

var commonSiteConfig = {
  linuxFxVersion: linuxFxVersion
  alwaysOn: true
  minTlsVersion: '1.2'
  ftpsState: 'Disabled'
  http20Enabled: true
  healthCheckPath: '/health'
  vnetRouteAllEnabled: true
}

resource prodApp 'Microsoft.Web/sites@2023-12-01' = {
  name: '${project}-prod-${nameSuffix}'
  location: location
  tags: union(tags, { environment: 'production', project: project, role: 'web' })
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: prodPlanId
    httpsOnly: true
    virtualNetworkSubnetId: prodAppsSubnetId
    siteConfig: commonSiteConfig
  }
}

resource stagingApp 'Microsoft.Web/sites@2023-12-01' = {
  name: '${project}-staging-${nameSuffix}'
  location: location
  tags: union(tags, { environment: 'staging', project: project, role: 'web' })
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: stagingPlanId
    httpsOnly: true
    virtualNetworkSubnetId: stagingAppsSubnetId
    siteConfig: commonSiteConfig
  }
}

resource prodServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = {
  name: prodPgServerName
}

resource stagingServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = {
  name: stagingPgServerName
}

resource prodDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: prodServer
  name: '${project}_prod'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource stagingDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: stagingServer
  name: '${project}_staging'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource prodRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignStorageRbac) {
  scope: storage
  name: guid(storage.id, prodApp.id, blobContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributorRoleId)
    principalId: prodApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource stagingRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignStorageRbac) {
  scope: storage
  name: guid(storage.id, stagingApp.id, blobContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributorRoleId)
    principalId: stagingApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output prodAppName string = prodApp.name
output stagingAppName string = stagingApp.name
output prodDbName string = prodDb.name
output stagingDbName string = stagingDb.name
