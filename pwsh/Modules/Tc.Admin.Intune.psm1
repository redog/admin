#requires -Modules Microsoft.Graph.DeviceManagement, Microsoft.Graph.Users, Microsoft.Graph.Devices.CorporateManagement

# Load shared context helper
$ctx = Join-Path $PSScriptRoot '../Private/Context.ps1'
if (Test-Path $ctx) { . $ctx }

function Get-IntuneDevice {
    <#
    .SYNOPSIS
        Lists Intune managed devices. Aliased as 'lsdevice'.
    #>
    [CmdletBinding()]
    param(
        [string]$Filter
    )
    begin {
        if (-not (Test-MgGraphContext -Scopes 'DeviceManagementManagedDevices.Read.All' -AutoConnect)) {
            return
        }
    }
    process {
        try {
            $params = @{ All = $true }
            if ($Filter) { $params.Filter = "startswith(deviceName, '$Filter')" }
            
            $devices = Get-MgDeviceManagementManagedDevice @params -ErrorAction Stop
            if ($null -eq $devices) {
                Write-Verbose "No Intune devices found."
                return
            }
            $devices | Select-Object Id, DeviceName, UserPrincipalName, OperatingSystem, ComplianceState, LastSyncDateTime | Write-Output
        }
        catch {
            Write-Error "An error occurred while fetching Intune devices: $($_.Exception.Message)"
        }
    }
}

function Invoke-IntuneDeviceWipe {
    <#
    .SYNOPSIS
        Initiates a remote wipe for an Intune device. Aliased as 'invwipe'.
    #>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('Id')]
        [string]$ManagedDeviceId,

        [switch]$KeepEnrollmentData
    )
    begin {
        if (-not (Test-MgGraphContext -Scopes 'DeviceManagementManagedDevices.PrivilegedOperations.All' -AutoConnect)) {
            return
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("device ID '$ManagedDeviceId'", "Remote Wipe")) {
            try {
                Invoke-MgWipeDeviceManagementManagedDevice -ManagedDeviceId $ManagedDeviceId -KeepEnrollmentData $KeepEnrollmentData -ErrorAction Stop
                Write-Host "Successfully initiated wipe." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to initiate wipe: $($_.Exception.Message)"
            }
        }
    }
}

function Get-UserDevices {
    <#
    .SYNOPSIS
        Lists Intune devices with robust filtering by user or device name. Aliased as 'lsdevices'.
    #>
    [CmdletBinding(DefaultParameterSetName = 'All')]
    param (
        [Parameter(ParameterSetName = 'ByUser', Mandatory = $true, Position = 0)]
        [string]$UserName,
        [Parameter(ParameterSetName = 'ByDevice', Mandatory = $true, Position = 0)]
        [string]$DeviceName,
        [Parameter(ParameterSetName = 'All')]
        [switch]$All,
        [Parameter()]
        [switch]$Detailed
    )

    begin {
        # Load shared context helper
        $ctx = Join-Path $PSScriptRoot '../Private/Context.ps1'
        if (Test-Path $ctx) { . $ctx }

        if (-not (Test-MgGraphContext -Scopes 'DeviceManagementManagedDevices.Read.All', 'User.Read.All' -AutoConnect)) {
            return
        }
    } process {
      try {
          $deviceParams = @{ All = $true; ExpandProperty = 'users' }
          $intuneDevices = @{}
          $entraDevices = @{}
          $userObj = $null

          # --- 1. Identify Target User (if applicable) ---
          if ($PSCmdlet.ParameterSetName -eq 'ByUser') {
              Write-Verbose "Resolving user '$UserName'..."
              $userObj = Get-MgUser -Filter "startswith(userPrincipalName, '$UserName') or startswith(displayName, '$UserName')" -ConsistencyLevel eventual -CountVariable c -ErrorAction SilentlyContinue | Select-Object -First 1

              if (-not $userObj) {
                  Write-Warning "User matching '$UserName' not found."
                  return
              }
              Write-Verbose "Target: $($userObj.DisplayName) ($($userObj.UserPrincipalName))"
          }
          # --- 2. Fetch Intune Devices ---
          Write-Verbose "Fetching Intune devices..."
          if ($userObj) {
              # Filter by UPN on device management entity
              $rawIntune = Get-MgDeviceManagementManagedDevice -Filter "userPrincipalName eq '$($userObj.UserPrincipalName)'" -ErrorAction SilentlyContinue
          } elseif ($PSCmdlet.ParameterSetName -eq 'ByDevice') {
               $deviceParams['Filter'] = "contains(deviceName, '$DeviceName')"
               $rawIntune = Get-MgDeviceManagementManagedDevice @deviceParams -ErrorAction Stop
          } else {
              $rawIntune = Get-MgDeviceManagementManagedDevice @deviceParams -ErrorAction Stop
          }
            
          if ($rawIntune) {
              foreach ($d in $rawIntune) {
                  # Key by AzureADDeviceId if present, else Serial
                  $key = if ($d.AzureADDeviceId) { $d.AzureADDeviceId } else { "SERIAL:" + $d.SerialNumber }
                  $intuneDevices[$key] = $d
              }
          }

          # --- 3. Fetch Entra Devices (User Mode Only for now, or careful Global) ---

          if ($userObj) {
              Write-Verbose "Fetching Entra devices owned/registered by user..."
              # Helper to process Entra list
              $processEntraList = {
                param($list)
                if ($list) {
                  foreach ($item in $list) {
                    # Just try to resolve as a device. Some directory objects might fail, which is fine (SilentlyContinue)
                    # We removed the OdataType check because it was missing on some valid objects
                    if (-not $entraDevices.ContainsKey($item.Id)) {
                      $fullEntra = Get-MgDevice -DeviceId $item.Id -ErrorAction SilentlyContinue
                      if ($fullEntra) { $entraDevices[$fullEntra.DeviceId] = $fullEntra }
                    }
                  }
                }
              }

              # 3a. Owned Devices
              $owned = Get-MgUserOwnedDevice -UserId $userObj.Id -All -ErrorAction SilentlyContinue
              & $processEntraList $owned

              # 3b. Registered Devices (Often different from Owned)
              $registered = Get-MgUserRegisteredDevice -UserId $userObj.Id -All -ErrorAction SilentlyContinue
              & $processEntraList $registered

          } elseif ($PSCmdlet.ParameterSetName -eq 'ByDevice') {
            # Search Entra by name
            $rawEntra = Get-MgDevice -Filter "startswith(displayName, '$DeviceName')" -ErrorAction SilentlyContinue
            foreach ($d in $rawEntra) { $entraDevices[$d.DeviceId] = $d }
          }

          # --- 4. Merge and Analyze ---
          $allKeys = ($intuneDevices.Keys + $entraDevices.Keys) | Select-Object -Unique
          foreach ($key in $allKeys) {
            $i = $intuneDevices[$key]
            $e = $entraDevices[$key]
            # Fallback: Check Entra directly for Intune items
            if ($i -and -not $e -and $i.AzureADDeviceId) {
                 Write-Verbose "Checking Entra directly for Intune device $($i.DeviceName)..."
                 $e = Get-MgDevice -Filter "deviceId eq '$($i.AzureADDeviceId)'" -ErrorAction SilentlyContinue | Select-Object -First 1
            }

            # Initialize standardized object structure
            $obj = [ordered]@{
                DeviceName      = if ($i) { $i.DeviceName } else { $e.DisplayName }
                SerialNumber    = if ($i) { $i.SerialNumber } else { "N/A" }
                Model           = if ($i) { $i.Model } else { $e.Model }
                User            = if ($i) { $i.UserPrincipalName } else { $userObj.UserPrincipalName }
                OS              = if ($i) { $i.OperatingSystem } else { $e.OperatingSystem }
                Source          = "Unknown"
                Warnings        = $null
                Id              = if ($i) { $i.Id } else { $null }
                EntraId         = if ($e) { $e.Id } else { $null }

                # Detailed fields (always present, null if unused, for consistent formatting)
                TotalStorageGB  = $null
                FreeStorageGB   = $null
                TotalMemoryGB   = $null
                LastSync        = $null
                Compliance      = $null
                Encrypted       = $null
                EthernetMac     = $null
                WiFiMac         = $null
                IPAddress       = $null
                EntraLastLogon  = $null
                TrustType       = $null
            }

            # Status Determination
            if ($i -and $e) {
                $obj.Source = "Managed (Intune + Entra)"
                if ($i.OperatingSystem -ne $e.OperatingSystem) {
                    $obj.Warnings = "OS Mismatch (Intune: $($i.OperatingSystem) / Entra: $($e.OperatingSystem))"
                }
            }
            elseif ($i) {
                $obj.Source = "Intune Only (Sync Issue?)"
                $obj.Warnings = "Missing in Entra (Check for deletion)"
            }
            elseif ($e) {
                $obj.Source = "Entra Only"
                $obj.TrustType = $e.TrustType
            }

            # Populate Detailed Stats
            if ($Detailed) {
                if ($i) {
                    $obj.TotalStorageGB = [math]::Round($i.TotalStorageSpaceInBytes / 1GB, 2)
                    $obj.FreeStorageGB  = [math]::Round($i.FreeStorageSpaceInBytes / 1GB, 2)
                    $obj.TotalMemoryGB  = [math]::Round($i.PhysicalMemoryInBytes / 1GB, 2)
                    $obj.LastSync       = $i.LastSyncDateTime
                    $obj.Compliance     = $i.ComplianceState
                    $obj.Encrypted      = $i.IsEncrypted

                    $obj.EthernetMac    = $i.EthernetMacAddress
                    $obj.WiFiMac        = $i.WiFiMacAddress
                    $obj.IPAddress      = $i.IpAddress
                }
                if ($e) {
                    $obj.EntraLastLogon = $e.ApproximateLastSignInDateTime
                }
            } else {
                # Remove detailed keys if not requested, to keep default view clean?
                # Actually, keeping them null is better for pipeline consistency, 
                # but for console output, we might want to hide them.
                # Let's keep them but depend on Format-Table to hide empty cols usually,
                # or user can Select-Object.
            }
            [PSCustomObject]$obj
          }
      } catch { 
        Write-Error "Failed to list devices: $($_.Exception.Message)" 
      }
    }
 }

function Get-TcDeviceDetail {
    <#
    .SYNOPSIS
        Gets a comprehensive cross-reference of a device across Autopilot, Intune, and Entra ID. Aliased as 'gdd'.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [string]$SerialNumber
    )
    begin {
        $scopes = @(
            'DeviceManagementServiceConfig.Read.All',
            'DeviceManagementManagedDevices.Read.All',
            'Device.Read.All'
        )
        if (-not (Test-MgGraphContext -Scopes $scopes -AutoConnect)) {
            return
        }
    }
    process {
        try {
            Write-Verbose "Searching for serial '$SerialNumber' across systems..."

            # Autopilot often fails on 'eq' for serials, use 'contains' and select first
            $autopilotDevice = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -Filter "contains(serialNumber, '$SerialNumber')" -ErrorAction SilentlyContinue | 
                Where-Object { $_.SerialNumber -eq $SerialNumber } | 
                Select-Object -First 1

            $intuneDevice = Get-MgDeviceManagementManagedDevice -Filter "serialNumber eq '$SerialNumber'" | Select-Object -First 1

            $entraDevice = $null
            $entraDeviceId = $intuneDevice.AzureADDeviceId
            if (-not $entraDeviceId) {
                $entraDeviceId = $autopilotDevice.AzureActiveDirectoryDeviceId
            }
            if ($entraDeviceId) {
                # Get-MgDevice -DeviceId expects the Object ID, not the Device ID. Use filter.
                $entraDevice = Get-MgDevice -Filter "deviceId eq '$entraDeviceId'" -ErrorAction SilentlyContinue | Select-Object -First 1
            }

            $result = [PSCustomObject]@{
                SerialNumber     = $SerialNumber
                Autopilot        = if ($autopilotDevice) { "Found ($($autopilotDevice.Id))" } else { "Not Found" }
                Intune           = if ($intuneDevice) { "Found ($($intuneDevice.DeviceName))" } else { "Not Found" }
                Entra            = if ($entraDevice) { "Found ($($entraDevice.DisplayName))" } else { "Not Found" }
                Status           = "Normal"
                AssignedUser     = $autopilotDevice.UserPrincipalName
                ManagedUser      = $intuneDevice.UserPrincipalName
                EntraTrustType   = $entraDevice.TrustType
                LastContact      = $autopilotDevice.LastContactedDateTime
                IntuneLastSync   = $intuneDevice.LastSyncDateTime
            }

            # Logic for "Ghost" detection
            if ($null -eq $intuneDevice -and ($null -ne $autopilotDevice -or $null -ne $entraDevice)) {
                $result.Status = "GHOST - Exists in Entra/Autopilot but NOT in Intune"
            }

            $result | Write-Output
        }
        catch {
            Write-Error "An error occurred while cross-referencing device: $($_.Exception.Message)"
        }
    }
}

Export-ModuleMember -Function `
    Get-IntuneDevice, Invoke-IntuneDeviceWipe, Get-TcDeviceDetail, Get-UserDevices `
  -Alias `
    lsdevice, invwipe, gdd, lsdevices

