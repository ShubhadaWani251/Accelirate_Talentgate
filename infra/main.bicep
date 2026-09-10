// =============================================================================
// AccelirateInternalProjects - shared platform (hardened)
//
// Deploys the shared resources once, then loops over `projects` to create a
// staging + production web app and a staging + production database for each
// project. Encodes the review recommendations as defaults:
//   - Private networking only (VNet integration + private endpoints); no public
//     DB/storage exposure and no AllowAll firewall rules.
//   - Production Postgres on General Purpose with zone-redundant HA, auto-grow,
//     geo-redundant backups; staging on a right-sized Burstable (not B1ms).
//   - App Service on Premium v3 (autoscale, slots, zone redundancy).
//   - Per-app system-assigned identity + Entra/RBAC to storage (no keys).
//   - Consistent naming + tags for cost allocation across shared resources.
//
// Deploy:
//   az deployment group create -g AccelirateInternalProjects \
//     -f infra/main.bicep -p pgAdminLogin=<user> pgAdminPassword=<secret>
// Preview first with `az deployment group what-if ... ` .
// =============================================================================

targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Short lowercase workload prefix used in resource names.')
@minLength(3)
@maxLength(16)
param workload string = 'accelinternal'

@description('Project short names. Each gets <name>-staging and <name>-prod web apps plus <name>_staging and <name>_prod databases.')
param projects array = [
  'apptitude'
  // 'projectb'
  // 'projectc'
]

@description('PostgreSQL administrator login.')
param pgAdminLogin string

@secure()
@description('PostgreSQL administrator password.')
param pgAdminPassword string

@description('Linux runtime stack for the web apps (e.g. PYTHON|3.13, NODE|20-lts).')
param linuxFxVersion string = 'PYTHON|3.13'

@description('Assign each app identity the Storage Blob Data Contributor role (requires the deployer to be Owner / User Access Administrator).')
param assignStorageRbac bool = true

@description('Tags applied to every resource.')
param tags object = {
  owner: 'Namrata'
  workload: 'AccelirateInternalProjects'
}

var suffix = take(uniqueString(resourceGroup().id), 6)

// ---------------------------------------------------------------------------
// Networking: one VNet, isolated subnets, private DNS. Keeps DB + storage off
// the public internet (fixes the AllowAll 0.0.0.0-255.255.255.255 exposure).
// A subnet can back only one App Service plan and one flexible server, so each
// gets its own delegated subnet.
// ---------------------------------------------------------------------------
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'vnet-${workload}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [ '10.20.0.0/16' ]
    }
    subnets: [
      {
        name: 'snet-apps-prod'
        properties: {
          addressPrefix: '10.20.1.0/24'
          delegations: [ { name: 'web', properties: { serviceName: 'Microsoft.Web/serverFarms' } } ]
        }
      }
      {
        name: 'snet-apps-staging'
        properties: {
          addressPrefix: '10.20.2.0/24'
          delegations: [ { name: 'web', properties: { serviceName: 'Microsoft.Web/serverFarms' } } ]
        }
      }
      {
        name: 'snet-pg-prod'
        properties: {
          addressPrefix: '10.20.3.0/24'
          delegations: [ { name: 'pg', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } } ]
        }
      }
      {
        name: 'snet-pg-staging'
        properties: {
          addressPrefix: '10.20.4.0/24'
          delegations: [ { name: 'pg', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } } ]
        }
      }
      {
        name: 'snet-pe'
        properties: {
          addressPrefix: '10.20.5.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

var appsProdSubnetId = '${vnet.id}/subnets/snet-apps-prod'
var appsStagingSubnetId = '${vnet.id}/subnets/snet-apps-staging'
var pgProdSubnetId = '${vnet.id}/subnets/snet-pg-prod'
var pgStagingSubnetId = '${vnet.id}/subnets/snet-pg-staging'
var peSubnetId = '${vnet.id}/subnets/snet-pe'

resource pgDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource pgDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: pgDns
  name: 'link-vnet'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource blobDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
  location: 'global'
  tags: tags
}

resource blobDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: blobDns
  name: 'link-vnet'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

// ---------------------------------------------------------------------------
// App Service plans: Premium v3 for autoscale, deployment slots and zone
// redundancy (Basic supported none of these). Prod is zone-redundant with 3
// instances; staging is a single smaller plan.
// ---------------------------------------------------------------------------
resource planProd 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${workload}-prod-plan'
  location: location
  tags: union(tags, { environment: 'production', role: 'web' })
  sku: {
    name: 'P2v3'
    tier: 'PremiumV3'
    capacity: 3
  }
  kind: 'linux'
  properties: {
    reserved: true
    zoneRedundant: true
  }
}

resource planStaging 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${workload}-staging-plan'
  location: location
  tags: union(tags, { environment: 'staging', role: 'web' })
  sku: {
    name: 'P1v3'
    tier: 'PremiumV3'
    capacity: 1
  }
  kind: 'linux'
  properties: {
    reserved: true
    zoneRedundant: false
  }
}

// ---------------------------------------------------------------------------
// PostgreSQL flexible servers (private access). Prod = General Purpose with
// zone-redundant HA; staging = Burstable B2ms (844 connections, vs 35 on the
// current B1ms). Both: auto-grow on, private DNS, no public network.
// ---------------------------------------------------------------------------
resource pgProd 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${workload}-prod-pg-${suffix}'
  location: location
  tags: union(tags, { environment: 'production', role: 'database' })
  sku: {
    name: 'Standard_D2ds_v5'
    tier: 'GeneralPurpose'
  }
  properties: {
    version: '18'
    administratorLogin: pgAdminLogin
    administratorLoginPassword: pgAdminPassword
    storage: {
      storageSizeGB: 128
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 30
      geoRedundantBackup: 'Enabled'
    }
    highAvailability: {
      mode: 'ZoneRedundant'
    }
    network: {
      delegatedSubnetResourceId: pgProdSubnetId
      privateDnsZoneArmResourceId: pgDns.id
    }
  }
  dependsOn: [ pgDnsLink ]
}

resource pgStaging 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${workload}-staging-pg-${suffix}'
  location: location
  tags: union(tags, { environment: 'staging', role: 'database' })
  sku: {
    name: 'Standard_B2ms'
    tier: 'Burstable'
  }
  properties: {
    version: '18'
    administratorLogin: pgAdminLogin
    administratorLoginPassword: pgAdminPassword
    storage: {
      storageSizeGB: 64
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 14
      geoRedundantBackup: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: pgStagingSubnetId
      privateDnsZoneArmResourceId: pgDns.id
    }
  }
  dependsOn: [ pgDnsLink ]
}

// ---------------------------------------------------------------------------
// Shared storage: keyless (Entra only), private endpoint, no public network.
// ---------------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${uniqueString(resourceGroup().id)}'
  location: location
  tags: union(tags, { environment: 'shared', role: 'storage' })
  sku: {
    name: 'Standard_GRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
    }
  }
}

resource storagePe 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: 'pe-${storage.name}-blob'
  location: location
  tags: tags
  properties: {
    subnet: { id: peSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: {
          privateLinkServiceId: storage.id
          groupIds: [ 'blob' ]
        }
      }
    ]
  }
}

resource storagePeDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: storagePe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: { privateDnsZoneId: blobDns.id }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Per-project resources: identical, repeatable pattern for every project.
// ---------------------------------------------------------------------------
module project 'modules/project.bicep' = [for name in projects: {
  name: 'project-${name}'
  params: {
    projectName: name
    location: location
    tags: tags
    nameSuffix: suffix
    linuxFxVersion: linuxFxVersion
    prodPlanId: planProd.id
    stagingPlanId: planStaging.id
    prodAppsSubnetId: appsProdSubnetId
    stagingAppsSubnetId: appsStagingSubnetId
    prodPgServerName: pgProd.name
    stagingPgServerName: pgStaging.name
    storageAccountName: storage.name
    assignStorageRbac: assignStorageRbac
  }
}]

output vnetId string = vnet.id
output prodPlan string = planProd.name
output stagingPlan string = planStaging.name
output prodPostgres string = pgProd.name
output stagingPostgres string = pgStaging.name
output storageAccount string = storage.name
