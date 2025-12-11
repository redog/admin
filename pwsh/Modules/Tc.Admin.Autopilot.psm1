#requires -Modules Microsoft.Graph.Authentication, Microsoft.Graph.DeviceManagement

function Get-AutopilotDevice {
    <#
    .SYNOPSIS
        Lists all registered Windows Autopilot devices. Aliased as 'lsap'.

    .DESCRIPTION
        Queries Microsoft Graph to get a list of all devices registered with the
        Windows Autopilot service, showing their serial number, assigned user, and group tag.
        Outputs raw device identity objects; enable -Verbose for progress information.

    .EXAMPLE
        PS C:\> lsap
        Lists all Autopilot devices in the tenant.
#>
    [CmdletBinding()]
    param()
    begin {
        if (-not (Ensure-MgGraphContext -Scopes 'DeviceManagementServiceConfig.Read.All' -AutoConnect)) {
            return
        }
    }
    process {
        try {
            Write-Verbose "Fetching all Autopilot device identities."
            $devices = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -All -ErrorAction Stop
            if ($null -eq $devices) {
                Write-Verbose "No Autopilot devices found."
                return
            }
            $devices | Select-Object Id, GroupTag, SerialNumber, UserPrincipalName | Write-Output
        }
        catch {
            Write-Error "An error occurred while fetching Autopilot devices: $($_.Exception.Message)"
        }
    }
}
function Set-AutopilotDeviceUser {
    <#
    .SYNOPSIS
        Assigns a user to an Autopilot device. Aliased as 'assignapusr'.

    .DESCRIPTION
        Assigns a primary user to a specific Autopilot device record using the device's ID.

    .PARAMETER DeviceId
        The ID of the Autopilot device. You can get this from 'lsap'.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to assign.

    .EXAMPLE
        PS C:\> assignapusr -DeviceId 'ztd-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' -UserPrincipalName "user@domain.com"
#>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipelineByPropertyName = $true)]
        [Alias('Id')]
        [string]$DeviceId,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$UserPrincipalName
    )
    begin {
        if (-not (Ensure-MgGraphContext -Scopes 'DeviceManagementServiceConfig.ReadWrite.All' -AutoConnect)) {
            return
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("device ID '$($DeviceId)'", "Assign user '$($UserPrincipalName)'")) {
            try {
                Write-Host "Assigning user '$($UserPrincipalName)' to device '$($DeviceId)'..." -ForegroundColor Yellow
                $uri = "https://graph.microsoft.com/v1.0/deviceManagement/windowsAutopilotDeviceIdentities/$DeviceId/assignUserToDevice"
                $body = @{ userPrincipalName = $UserPrincipalName } | ConvertTo-Json
                Invoke-MgGraphRequest -Method POST -Uri $uri -Body $body -ErrorAction Stop
                Write-Host "Successfully assigned user." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to assign user: $($_.Exception.Message)"
            }
        }
    }
}

function Remove-AutopilotDeviceUser {
    <#
    .SYNOPSIS
        Removes the assigned user from an Autopilot device. Aliased as 'rmapuser'.

    .DESCRIPTION
        Removes the primary user assignment from a specific Autopilot device record.

    .PARAMETER DeviceId
        The ID of the Autopilot device. You can get this from 'lsap'.

    .EXAMPLE
        PS C:\> rmapuser -DeviceId 'ztd-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
#>
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('Id')]
        [string]$DeviceId
    )
    begin {
        if (-not (Ensure-MgGraphContext -Scopes 'DeviceManagementServiceConfig.ReadWrite.All' -AutoConnect)) {
            return
        }
    }
    process {
         if ($PSCmdlet.ShouldProcess("device ID '$($DeviceId)'", "Remove assigned user")) {
            try {
                Write-Host "Removing assigned user from device '$($DeviceId)'..." -ForegroundColor Yellow
                $uri = "https://graph.microsoft.com/v1.0/deviceManagement/windowsAutopilotDeviceIdentities/$DeviceId/unassignUserFromDevice"
                Invoke-MgGraphRequest -Method POST -Uri $uri -ErrorAction Stop
                Write-Host "Successfully removed user assignment." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to remove user assignment: $($_.Exception.Message)"
            }
        }
    }
}


Export-ModuleMember -Function `
    Get-AutopilotDevice, Set-AutopilotDeviceUser, Remove-AutopilotDeviceUser `
  -Alias `
    lsap, assignapusr, rmapuser

