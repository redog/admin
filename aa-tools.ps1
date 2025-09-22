<#
.SYNOPSIS
  A collection of REPL-friendly functions to interact with Azure Automation.

.DESCRIPTION
  This script provides a lightweight "shell" experience for managing and running
  Azure Automation runbooks directly from the PowerShell command line.

  To use, configure the variables in the CONFIGURATION section and dot-source this
  file in your PowerShell session or profile:
  . C:\path\to\aa-tools.ps1

.NOTES
  Author: Eric Ortego / Gemini / Jules / Codex
  Version: 1.0
#>

#requires -Modules Az.Accounts, Az.Automation 
# Mg... etc...

# --- CONFIGURATION ---
# For persistent use, load these in your $PROFILE script before dot-sourcing this file.
#$Script:AutomationAccountName = "Automate-contoso"
#$Script:AutomationResourceGroupName = "AACRG"
# --- END CONFIGURATION ---


function Get-AutomationRunbookInfo {
    <#
    .SYNOPSIS
        Lists runbooks and their parameters. Aliased as 'lsrb'.

    .DESCRIPTION
        Provides a quick way to list all runbooks in the configured Automation Account
        or inspect the parameters of a specific runbook.

    .PARAMETER Name
        The name of a specific runbook to inspect.

    .PARAMETER Parameters
        A switch that, when used with -Name, displays the parameters of the specified runbook.

    .EXAMPLE
        PS C:\> lsrb
        Lists all runbooks in the configured automation account.

    .EXAMPLE
        PS C:\> lsrb -Name "Restart-Service"
        Gets detailed information for the "Restart-Service" runbook.

    .EXAMPLE
        PS C:\> lsrb -Name "Restart-Service" -Parameters
        Displays the parameters (name, type, mandatory, default value) for the "Restart-Service" runbook.
#>
    [CmdletBinding(DefaultParameterSetName = 'List')]
    param (
        [Parameter(Mandatory = $false, Position = 0, ParameterSetName = 'Inspect')]
        [string]$Name,

        [Parameter(Mandatory = $true, ParameterSetName = 'Inspect')]
        [switch]$Parameters
    )

    begin {
        # Check for Azure connection
        if (-not (Get-AzContext)) {
            Write-Warning "No active Azure context. Run Connect-AzAccount."
            Connect-AzAccount -ErrorAction Stop
        }
        # Check if config is set
        if ([string]::IsNullOrWhiteSpace($Script:AutomationAccountName) -or $Script:AutomationAccountName -eq "YourAutomationAccountName") {
            Write-Error "Configuration needed. Please set `$Script:AutomationAccountName and `$Script:AutomationResourceGroupName in the script file."
            return # Stop processing
        }
    }

    process {
        try {
            if ($PSCmdlet.ParameterSetName -eq 'List') {
                # List all runbooks
                Get-AzAutomationRunbook -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName |
                    Select-Object Name, State, LastModifiedTime, CreationTime
            }
            elseif ($Parameters.IsPresent) {
                # Display parameters for a specific runbook
                Write-Host "Parameters for '$($Name)':" -ForegroundColor Cyan
                $runbook = Get-AzAutomationRunbook -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -Name $Name
                if ($runbook.Parameters.Count -eq 0) {
                    Write-Host "  No parameters found."
                }
                else {
                    $runbook.Parameters.GetEnumerator() | ForEach-Object {
                        [PSCustomObject]@{
                            Name        = $_.Name
                            Type        = $_.Value.Type
                            Mandatory   = $_.Value.IsMandatory
                            Default     = $_.Value.DefaultValue
                        }
                    } | Format-Table -AutoSize
                }
            }
            else {
                # Get details for a specific runbook
                Get-AzAutomationRunbook -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -Name $Name
            }
        }
        catch {
            Write-Error $_.Exception.Message
        }
    }
}

function Invoke-AutomationRunbook {
    param (
        [Parameter(Mandatory=$true)]
        [string]$RunbookName,

        [Parameter(Mandatory=$false)]
        [string]$HybridRunner,

        [Parameter(Mandatory=$false)]
        [hashtable]$Parameters = @{}
    )

    # Variables
    $AutomationAccountName = "Automate-1dd430f4-29c2-4702-8e8f-26737150a8eb-EUS"
    $RGName = "DefaultResourceGroup-EUS"

    # Start Runbook
    Write-Host "Starting runbook '$RunbookName'..." -ForegroundColor Cyan
    if ($HybridRunner) {
        Write-Host "Using hybrid worker: $HybridRunner" -ForegroundColor Cyan
    }

    try {
        # Start the runbook and store the job object
        $startParams = @{
            ResourceGroupName = $RGName
            AutomationAccountName = $AutomationAccountName
            Name = $RunbookName
            ErrorAction = 'Stop'
        }

        if ($HybridRunner) {
            $startParams['RunOn'] = $HybridRunner
        }

        if ($Parameters.Count -gt 0) {
            $startParams['Parameters'] = $Parameters
        }

        $job = Start-AzAutomationRunbook @startParams
        Write-Host "Runbook started successfully. Job ID: $($job.JobId). Waiting for completion..." -ForegroundColor Cyan
    } catch {
        Write-Error "Failed to start runbook '$RunbookName': $($_.Exception.Message)"
        return
    }

    # Wait for job completion
    Write-Host "Monitoring job status..." -ForegroundColor Gray
    while ($true) {
        try {
            $job = Get-AzAutomationJob -ResourceGroupName $RGName -AutomationAccountName $AutomationAccountName -Id $job.JobId -ErrorAction Stop

            if ($job.Status -in @("Completed", "Failed", "Suspended", "Stopped")) {
                break
            }

            Start-Sleep -Seconds 5
        } catch {
            Write-Error "Failed to get job status for Job ID $($job.JobId): $($_.Exception.Message)"
            Start-Sleep -Seconds 15
        }
    }

    # Display final status
    $statusColor = if ($job.Status -eq "Completed") { "Green" } else { "Red" }
    Write-Host "Runbook finished with status: $($job.Status)" -ForegroundColor $statusColor

    # If the job failed, print the exception
    if ($job.Status -eq "Failed") {
        if ($job.Exception) {
            Write-Host "Runbook Exception: $($job.Exception)" -ForegroundColor Red
        }
    }
    Write-Host ""

    # Define colors for different output streams
    $streamColors = @{
        "Output"  = "White"
        "Verbose" = "Cyan"
        "Warning" = "Yellow"
        "Error"   = "Red"
        "Debug"   = "Magenta"
        "Progress"= "Gray"
    }

    # Fetch and display outputs for relevant streams
    foreach ($stream in @("Output", "Verbose", "Warning", "Error")) {
        if ($streamColors.ContainsKey($stream)) {
            $color = $streamColors[$stream]
        } else {
            $color = "White"
        }

        Write-Host "===== $stream Stream =====" -ForegroundColor $color

        try {
            $streamOutput = Get-AzAutomationJobOutput -ResourceGroupName $RGName -AutomationAccountName $AutomationAccountName -Id $job.JobId -Stream $stream -ErrorAction Stop

            if ($streamOutput) {
                foreach ($entry in $streamOutput) {
                    try {
                        $record = Get-AzAutomationJobOutputRecord -ResourceGroupName $RGName -AutomationAccountName $AutomationAccountName -JobId $job.JobId -Id $entry.StreamRecordId -ErrorAction Stop

                        if ($null -ne $record.Value) {
                            if ($stream -eq "Verbose") {
                                $messageToPrint = $record.Value.Message
                                if ($null -ne $messageToPrint) {
                                    Write-Host $messageToPrint -ForegroundColor $color
                                }
                            } else {
                                Write-Host $record.Value -ForegroundColor $color
                            }
                        }
                    } catch {
                        Write-Warning "Could not retrieve details for stream record ID $($entry.StreamRecordId) in stream '$stream': $($_.Exception.Message)"
                    }
                }
            }
        } catch {
            Write-Warning "Could not retrieve output for stream '$stream': $($_.Exception.Message)"
        }
        Write-Host ""
    }
    Write-Host ""
}

function Get-UserDevices {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $false, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [string]$UserPrincipalName
    )

    process {
        try {
            $selectProperties = @(
                "deviceName",
                "serialNumber",
                "manufacturer",
                "model",
                "userPrincipalName" # Included for the 'all users' scenario
            )

            if (-not [string]::IsNullOrWhiteSpace($UserPrincipalName)) {
                Write-Verbose "Attempting to retrieve devices for user: $UserPrincipalName"
                # Get the user object to ensure the UPN is valid and to get the ID
                try {
                    $user = Get-MgUser -UserId $UserPrincipalName -ErrorAction Stop -Property "Id"
                    Write-Verbose "Found user with ID: $($user.Id)"
                }
                catch {
                    Write-Error "User '$UserPrincipalName' not found or error retrieving user: $($_.Exception.Message)"
                    return
                }

                # Retrieve managed devices for the specified user
                $devices = Get-MgUserManagedDevice -UserId $user.Id -Property $selectProperties -ErrorAction Stop -All
                if ($null -eq $devices -or $devices.Count -eq 0) {
                    Write-Host "No managed devices found for $UserPrincipalName."
                    return
                }
            }
            else {
                Write-Verbose "Attempting to retrieve all managed devices."
                # Retrieve all managed devices
                $devices = Get-MgDeviceManagementManagedDevice -Property $selectProperties -ErrorAction Stop -All
                if ($null -eq $devices -or $devices.Count -eq 0) {
                    Write-Host "No managed devices found in the tenant."
                    return
                }
            }

            $output = @()
            foreach ($device in $devices) {
                $output += [PSCustomObject]@{
                    UserPrincipalName = if (-not [string]::IsNullOrWhiteSpace($UserPrincipalName)) { $UserPrincipalName } else { $device.UserPrincipalName }
                    DeviceName        = $device.DeviceName
                    SerialNumber      = $device.SerialNumber
                    Brand             = $device.Manufacturer
                    Model             = $device.Model
                }
            }

            return $output | Select-Object UserPrincipalName, DeviceName, SerialNumber, Brand, Model

        }
        catch {
            Write-Error "An error occurred: $($_.Exception.Message)"
            Write-Error "Stack Trace: $($_.ScriptStackTrace)"
        }
    }
}

function Get-IntuneUserDevice {
    <#
    .SYNOPSIS
        Lists the Intune-managed devices for a specific user. Aliased as 'lsdevice'.

    .DESCRIPTION
        Queries Microsoft Graph to find all devices enrolled in Intune for a given user.
        The output includes the device ID, which is required for other device actions.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to query.

    .EXAMPLE
        PS C:\> lsdevice "user@domain.com"
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true)]
        [string]$UserPrincipalName
    )
    begin {
        if (-not (Get-MgContext)) {
            Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes 'DeviceManagementManagedDevices.Read.All'"
            Connect-MgGraph -Scopes 'DeviceManagementManagedDevices.Read.All' -ErrorAction Stop
        }
    }
    process {
        try {
            Write-Host "Finding Intune devices for '$($UserPrincipalName)'..." -ForegroundColor Yellow
            $devices = Get-MgDeviceManagementManagedDevice -Filter "userPrincipalName eq '$($UserPrincipalName)'" -ErrorAction Stop
            if ($null -eq $devices) {
                Write-Host "No Intune-managed devices found for this user."
                return
            }
            $devices | Select-Object DeviceName, Id, OperatingSystem, ComplianceState, ManagedDeviceOwnerType
        }
        catch {
            Write-Error "Could not retrieve devices for '$($UserPrincipalName)': $($_.Exception.Message)"
        }
    }
}

function Invoke-IntuneDeviceAction {
    <#
    .SYNOPSIS
        Performs a remote action on an Intune-managed device. Aliased as 'invdevice'.

    .DESCRIPTION
        Sends a remote command, such as 'remoteLock' or 'rebootNow', to a specific device via Intune.
        You must provide the unique ID of the managed device.

    .PARAMETER DeviceId
        The ID of the managed device. You can get this from 'lsdevice'.

    .PARAMETER ActionName
        The remote action to perform. Valid options are 'remoteLock' and 'rebootNow'.

    .EXAMPLE
        PS C:\> invdevice -DeviceId 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' -ActionName remoteLock

    .EXAMPLE
        PS C:\> lsdevice "user@domain.com" | Select-Object -First 1 | invdevice -ActionName rebootNow
#>
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('Id')]
        [string]$DeviceId,

        [Parameter(Mandatory = $true, Position = 1)]
        [ValidateSet('remoteLock', 'rebootNow')]
        [string]$ActionName
    )
    begin {
        if (-not (Get-MgContext)) {
            Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes 'DeviceManagementManagedDevices.ReadWrite.All'"
            Connect-MgGraph -Scopes 'DeviceManagementManagedDevices.ReadWrite.All' -ErrorAction Stop
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("device with ID '$($DeviceId)'", "Perform Action: $($ActionName)")) {
            try {
                Write-Host "Sending '$($ActionName)' command to device '$($DeviceId)'..." -ForegroundColor Yellow
                $uri = "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices/$DeviceId/$ActionName"
                Invoke-MgGraphRequest -Method POST -Uri $uri -ErrorAction Stop
                Write-Host "Successfully sent '$($ActionName)' command." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to perform action '$($ActionName)' on device '$($DeviceId)': $($_.Exception.Message)"
            }
        }
    }
}

function Get-IntuneDeviceActionStatus {
    <#
    .SYNOPSIS
        Shows the status of recent Intune device actions for a specific device. Aliased as 'lsdevaction'.

    .DESCRIPTION
        Queries the device object directly to show the status of recent device management actions.
        Note: This uses the 'beta' Graph API endpoint, as the 'deviceActionResults' property
        is not available in v1.0.

    .PARAMETER DeviceId
        The ID of the managed device to check. Can be piped from 'lsdevice'.

    .EXAMPLE
        PS C:\> lsdevaction -DeviceId 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
        Shows the status of recent actions for the specified device.

    .EXAMPLE
        PS C:\> lsdevice user@domain.com | Select-Object -First 1 | lsdevaction
        Gets the first device for a user and shows the last two actions for it.
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('Id')]
        [string]$DeviceId
    )
    begin {
        if (-not (Get-MgContext)) {
            Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes 'DeviceManagementManagedDevices.Read.All'"
            Connect-MgGraph -Scopes 'DeviceManagementManagedDevices.Read.All' -ErrorAction Stop
        }
    }
    process {
        try {
            Write-Host "Fetching action results for device '$($DeviceId)'..." -ForegroundColor Yellow

            # This information is on the device object itself, in the 'deviceActionResults' property.
            # This requires using the 'beta' endpoint.
            $uri = "https://graph.microsoft.com/beta/deviceManagement/managedDevices/$DeviceId`?`$select=deviceName,deviceActionResults"
            $device = Invoke-MgGraphRequest -Method GET -Uri $uri -ErrorAction Stop

            if ($null -eq $device.deviceActionResults) {
                Write-Host "No action results found for device ID '$DeviceId'."
                return
            }

            # Format the output for readability, sorting by the most recent
            $device.deviceActionResults |
                Sort-Object lastUpdatedDateTime -Descending |
                Select-Object actionName, actionState, lastUpdatedDateTime |
                Format-Table -AutoSize
        }
        catch {
            Write-Error "An error occurred while fetching device action status: $($_.Exception.Message)"
        }
    }
}

function Get-UserGroupMembership {
    <#
    .SYNOPSIS
        Lists the group memberships for a user. Aliased as 'lsgrp'.

    .DESCRIPTION
        Queries Microsoft Graph to find all groups a user is a member of.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to query.

    .EXAMPLE
        PS C:\> lsgrp "user@domain.com"
    .TODO
       Not listing names and other properties properly
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [string]$UserPrincipalName
    )
    begin {
        if (-not (Get-MgContext)) {
            Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes 'User.Read.All', 'GroupMember.Read.All'"
            Connect-MgGraph -Scopes 'User.Read.All', 'GroupMember.Read.All' -ErrorAction Stop
        }
    }
    process {
        try {
            Write-Host "Fetching group memberships for '$($UserPrincipalName)'..." -ForegroundColor Yellow
            $groups = Get-MgUserMemberOf -UserId $UserPrincipalName -ErrorAction Stop
            if ($null -eq $groups) {
                Write-Host "User is not a member of any groups."
                return
            }
            $groups | Select-Object DisplayName, Id, Description
        }
        catch {
            Write-Error "An error occurred while fetching groups for '$($UserPrincipalName)': $($_.Exception.Message)"
        }
    }
}

function Add-UserToGroup {
    <#
    .SYNOPSIS
        Adds a user to a group. Aliased as 'addgrp'.

    .DESCRIPTION
        Adds a specified user to a specified group using their UPN and the group's display name or ID.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to add.

    .PARAMETER GroupIdentifier
        The display name or ID of the group.

    .EXAMPLE
        PS C:\> addgrp "user@domain.com" -GroupIdentifier "All Staff"
#>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$UserPrincipalName,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$GroupIdentifier
    )
    begin {
        if (-not (Get-MgContext)) {
            Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes 'User.Read.All', 'GroupMember.ReadWrite.All'"
            Connect-MgGraph -Scopes 'User.Read.All', 'GroupMember.ReadWrite.All' -ErrorAction Stop
        }
    }
    process {
        try {
            # Find the user to get their ID
            $user = Get-MgUser -UserId $UserPrincipalName -ErrorAction Stop -Property Id
            if (-not $user) {
                Write-Error "User '$($UserPrincipalName)' not found."
                return
            }

            # Find the group by ID or DisplayName
            $group = $null
            try {
                # First, try treating the identifier as a GUID (ID)
                $group = Get-MgGroup -GroupId $GroupIdentifier -ErrorAction SilentlyContinue
            } catch {}

            if (-not $group) {
                # If that fails, try searching by display name
                $foundGroups = Get-MgGroup -Filter "displayName eq '$($GroupIdentifier)'" -ErrorAction Stop
                if ($foundGroups.Count -eq 1) {
                    $group = $foundGroups
                } elseif ($foundGroups.Count -gt 1) {
                    Write-Error "Multiple groups found with the name '$($GroupIdentifier)'. Please use the group ID."
                    return
                } else {
                    Write-Error "Group '$($GroupIdentifier)' not found."
                    return
                }
            }

            if ($PSCmdlet.ShouldProcess("user '$($user.UserPrincipalName)' to group '$($group.DisplayName)'", "Add Membership")) {
                Write-Host "Adding '$($user.UserPrincipalName)' to group '$($group.DisplayName)'..." -ForegroundColor Yellow
                New-MgGroupMember -GroupId $group.Id -DirectoryObjectId $user.Id -ErrorAction Stop
                Write-Host "Successfully added user to group." -ForegroundColor Green
            }
        }
        catch {
            Write-Error "An error occurred: $($_.Exception.Message)"
        }
    }
}

function Remove-UserFromGroup {
    <#
    .SYNOPSIS
        Removes a user from a group. Aliased as 'remgrp'.

    .DESCRIPTION
        Removes a specified user from a specified group using their UPN and the group's display name or ID.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to remove.

    .PARAMETER GroupIdentifier
        The display name or ID of the group.

    .EXAMPLE
        PS C:\> remgrp "user@domain.com" -GroupIdentifier "Former Staff"
#>
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$UserPrincipalName,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$GroupIdentifier
    )
    begin {
        if (-not (Get-MgContext)) {
            Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes 'User.Read.All', 'GroupMember.ReadWrite.All'"
            Connect-MgGraph -Scopes 'User.Read.All', 'GroupMember.ReadWrite.All' -ErrorAction Stop
        }
    }
    process {
        try {
            # Find the user to get their ID
            $user = Get-MgUser -UserId $UserPrincipalName -ErrorAction Stop -Property Id
            if (-not $user) {
                Write-Error "User '$($UserPrincipalName)' not found."
                return
            }

            # Find the group by ID or DisplayName
            $group = $null
            try {
                $group = Get-MgGroup -GroupId $GroupIdentifier -ErrorAction SilentlyContinue
            } catch {}

            if (-not $group) {
                $foundGroups = Get-MgGroup -Filter "displayName eq '$($GroupIdentifier)'" -ErrorAction Stop
                if ($foundGroups.Count -eq 1) {
                    $group = $foundGroups
                } elseif ($foundGroups.Count -gt 1) {
                    Write-Error "Multiple groups found with name '$($GroupIdentifier)'. Please use the group ID."
                    return
                } else {
                    Write-Error "Group '$($GroupIdentifier)' not found."
                    return
                }
            }

            # We need the user's membership ID within the group to remove them
            $membership = Get-MgGroupMember -GroupId $group.Id -Filter "id eq '$($user.Id)'" -ErrorAction Stop
            if (-not $membership) {
                Write-Warning "User '$($user.UserPrincipalName)' is not a member of group '$($group.DisplayName)'."
                return
            }

            if ($PSCmdlet.ShouldProcess("user '$($user.UserPrincipalName)' from group '$($group.DisplayName)'", "Remove Membership")) {
                Write-Host "Removing '$($user.UserPrincipalName)' from group '$($group.DisplayName)'..." -ForegroundColor Yellow
                Remove-MgGroupMemberByRef -GroupId $group.Id -DirectoryObjectId $user.Id -ErrorAction Stop
                Write-Host "Successfully removed user from group." -ForegroundColor Green
            }
        }
        catch {
            Write-Error "An error occurred: $($_.Exception.Message)"
        }
    }
}


function Get-AutopilotDevice {
    <#
    .SYNOPSIS
        Lists all registered Windows Autopilot devices. Aliased as 'lsap'.

    .DESCRIPTION
        Queries Microsoft Graph to get a list of all devices registered with the
        Windows Autopilot service, showing their serial number, assigned user, and group tag.

    .EXAMPLE
        PS C:\> lsap
        Lists all Autopilot devices in the tenant.
#>
    [CmdletBinding()]
    param()
    begin {
        if (-not (Get-MgContext)) {
            Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes 'DeviceManagementServiceConfig.Read.All'"
            Connect-MgGraph -Scopes 'DeviceManagementServiceConfig.Read.All' -ErrorAction Stop
        }
    }
    process {
        try {
            Write-Host "Fetching all Autopilot device identities..." -ForegroundColor Yellow
            $devices = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -All -ErrorAction Stop
            if ($null -eq $devices) {
                Write-Host "No Autopilot devices found."
                return
            }
            $devices | Select-Object Id, GroupTag, SerialNumber, UserPrincipalName
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
        if (-not (Get-MgContext)) {
            Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes 'DeviceManagementServiceConfig.ReadWrite.All'"
            Connect-MgGraph -Scopes 'DeviceManagementServiceConfig.ReadWrite.All' -ErrorAction Stop
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
        if (-not (Get-MgContext)) {
            Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes 'DeviceManagementServiceConfig.ReadWrite.All'"
            Connect-MgGraph -Scopes 'DeviceManagementServiceConfig.ReadWrite.All' -ErrorAction Stop
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

function Get-AutomationWebhook {
    <#
    .SYNOPSIS
        Lists webhooks for a specific runbook. Aliased as 'lswebhook'.

    .DESCRIPTION
        Retrieves all webhooks associated with a given runbook in the configured Automation Account.

    .PARAMETER RunbookName
        The name of the runbook to inspect for webhooks.

    .EXAMPLE
        PS C:\> lswebhook -RunbookName "Restart-Service"
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$RunbookName
    )
    begin {
        if (-not (Get-AzContext)) {
            Write-Warning "No active Azure context. Run Connect-AzAccount."
            Connect-AzAccount -ErrorAction Stop
        }
    }
    process {
        try {
            Write-Host "Getting webhooks for runbook '$($RunbookName)'..." -ForegroundColor Yellow
            $webhooks = Get-AzAutomationWebhook -RunbookName $RunbookName -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -ErrorAction Stop
            if ($null -eq $webhooks) {
                Write-Host "No webhooks found for this runbook."
                return
            }
            $webhooks | Select-Object Name, IsEnabled, ExpiryTime, LastModifiedTime
        }
        catch {
            Write-Error "An error occurred while fetching webhooks: $($_.Exception.Message)"
        }
    }
}

function New-AutomationWebhook {
    <#
    .SYNOPSIS
        Creates a new webhook for an Automation runbook. Aliased as 'addwebhook'.

    .DESCRIPTION
        Creates a new webhook, sets its expiration, and immediately returns the webhook URI.
        The URI is only available at the time of creation and cannot be retrieved later.

    .PARAMETER RunbookName
        The name of the runbook to attach the webhook to.

    .PARAMETER WebhookName
        The desired name for the new webhook.

    .PARAMETER ExpiryTime
        The date and time when the webhook will expire. Defaults to one year from creation.

    .PARAMETER Disabled
        A switch to create the webhook in a disabled state.

    .EXAMPLE
        PS C:\> addwebhook "Restart-Service" -WebhookName "ServiceRestartAPI"
        Creates a new webhook named 'ServiceRestartAPI' that expires in one year.

    .EXAMPLE
        PS C:\> $expiry = (Get-Date).AddDays(30)
        PS C:\> addwebhook "MyRunbook" -WebhookName "TempHook" -ExpiryTime $expiry -Disabled
        Creates a disabled webhook that expires in 30 days.
#>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$RunbookName,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$WebhookName,

        [Parameter(Mandatory = $false)]
        [datetime]$ExpiryTime = (Get-Date).AddYears(1),

        [Parameter(Mandatory = $false)]
        [switch]$Disabled
    )
    begin {
        if (-not (Get-AzContext)) {
            Write-Warning "No active Azure context. Run Connect-AzAccount."
            Connect-AzAccount -ErrorAction Stop
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("runbook '$($RunbookName)'", "Create webhook '$($WebhookName)'")) {
            try {
                $splat = @{
                    Name                  = $WebhookName
                    RunbookName           = $RunbookName
                    IsEnabled             = -not $Disabled.IsPresent
                    ExpiryTime            = $ExpiryTime
                    ResourceGroupName     = $Script:AutomationResourceGroupName
                    AutomationAccountName = $Script:AutomationAccountName
                }
                $newWebhook = New-AzAutomationWebhook @splat -ErrorAction Stop

                Write-Host "`n" + ("-"*60)
                Write-Host "Webhook '$($WebhookName)' created successfully!" -ForegroundColor Green
                Write-Host "IMPORTANT: Copy the Webhook URI below. It cannot be retrieved again." -ForegroundColor Yellow
                Write-Host ("-"*60)

                # Output an object containing the URI for easy copying or programmatic use
                $newWebhook | Select-Object Name, IsEnabled, ExpiryTime, WebhookUri
            }
            catch {
                Write-Error "Failed to create webhook: $($_.Exception.Message)"
            }
        }
    }
}

function Remove-AutomationWebhook {
    <#
    .SYNOPSIS
        Removes a webhook from an Automation runbook. Aliased as 'remwebhook'.

    .DESCRIPTION
        Deletes a webhook from a specified runbook. This action is irreversible.

    .PARAMETER RunbookName
        The name of the runbook from which to remove the webhook.

    .PARAMETER WebhookName
        The name of the webhook to remove.

    .EXAMPLE
        PS C:\> remwebhook "Restart-Service" -WebhookName "OldHook"
#>
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$RunbookName,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$WebhookName
    )
    begin {
        if (-not (Get-AzContext)) {
            Write-Warning "No active Azure context. Run Connect-AzAccount."
            Connect-AzAccount -ErrorAction Stop
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("webhook '$($WebhookName)' from runbook '$($RunbookName)'", "Remove")) {
            try {
                Remove-AzAutomationWebhook -Name $WebhookName -RunbookName $RunbookName -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -ErrorAction Stop
                Write-Host "Successfully removed webhook '$($WebhookName)'." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to remove webhook: $($_.Exception.Message)"
            }
        }
    }
}

function Get-AutomationVariable {
    <#
    .SYNOPSIS
        Lists Automation Account variables. Aliased as 'lsvariable'.

    .DESCRIPTION
        Retrieves one or all variables from the configured Automation Account.

    .PARAMETER Name
        The name of a specific variable to retrieve.

    .EXAMPLE
        PS C:\> lsvariable
        Lists all variables in the account.

    .EXAMPLE
        PS C:\> lsvariable -Name "MySecret"
        Gets the details for a specific variable (value will be null if encrypted).
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false, Position = 0)]
        [string]$Name
    )
    begin {
        if (-not (Get-AzContext)) {
            Write-Warning "No active Azure context. Run Connect-AzAccount."
            Connect-AzAccount -ErrorAction Stop
        }
    }
    process {
        try {
            $splat = @{
                ResourceGroupName     = $Script:AutomationResourceGroupName
                AutomationAccountName = $Script:AutomationAccountName
            }
            if ($PSBoundParameters.ContainsKey('Name')) {
                Write-Host "Getting variable '$($Name)'..." -ForegroundColor Yellow
                $splat['Name'] = $Name
            } else {
                Write-Host "Getting all variables..." -ForegroundColor Yellow
            }

            $variables = Get-AzAutomationVariable @splat -ErrorAction Stop
            if ($null -eq $variables) {
                Write-Host "No variables found."
                return
            }
            $variables | Select-Object Name, Description, IsEncrypted, LastModifiedTime
        }
        catch {
            Write-Error "An error occurred while fetching variables: $($_.Exception.Message)"
        }
    }
}

function New-AutomationVariable {
    <#
    .SYNOPSIS
        Creates a new Automation Account variable. Aliased as 'addvariable'.

    .DESCRIPTION
        Creates a new, optionally encrypted, variable in the configured Automation Account.

    .PARAMETER Name
        The name for the new variable.

    .PARAMETER Value
        The value to store in the variable.

    .PARAMETER Description
        An optional description for the variable.

    .PARAMETER Encrypted
        A switch to encrypt the variable.

    .EXAMPLE
        PS C:\> addvariable -Name "ApiEndpoint" -Value "https://api.example.com" -Description "Main API endpoint URL."

    .EXAMPLE
        PS C:\> addvariable -Name "ApiKey" -Value "super-secret-key" -Encrypted
        Creates a new encrypted variable.
#>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Name,

        [Parameter(Mandatory = $true, Position = 1)]
        [object]$Value,

        [Parameter(Mandatory = $false)]
        [string]$Description,

        [Parameter(Mandatory = $false)]
        [switch]$Encrypted
    )
    begin {
        if (-not (Get-AzContext)) {
            Write-Warning "No active Azure context. Run Connect-AzAccount."
            Connect-AzAccount -ErrorAction Stop
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("variable '$($Name)'", "Create")) {
            try {
                $splat = @{
                    Name                  = $Name
                    Value                 = $Value
                    Encrypted             = $Encrypted.IsPresent
                    ResourceGroupName     = $Script:AutomationResourceGroupName
                    AutomationAccountName = $Script:AutomationAccountName
                }
                if ($PSBoundParameters.ContainsKey('Description')) {
                    $splat['Description'] = $Description
                }

                New-AzAutomationVariable @splat -ErrorAction Stop
                Write-Host "Successfully created variable '$($Name)'." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to create variable: $($_.Exception.Message)"
            }
        }
    }
}

function Set-AutomationVariable {
    <#
    .SYNOPSIS
        Updates the value of an Automation Account variable. Aliased as 'setvariable'.

    .DESCRIPTION
        Changes the value of an existing variable. Note: You cannot change the encrypted state.

    .PARAMETER Name
        The name of the variable to update.

    .PARAMETER Value
        The new value for the variable.

    .EXAMPLE
        PS C:\> setvariable -Name "ApiEndpoint" -Value "https://api-v2.example.com"
#>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Name,

        [Parameter(Mandatory = $true, Position = 1)]
        [object]$Value
    )
    begin {
        if (-not (Get-AzContext)) {
            Write-Warning "No active Azure context. Run Connect-AzAccount."
            Connect-AzAccount -ErrorAction Stop
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("variable '$($Name)'", "Update value")) {
            try {
                Set-AzAutomationVariable -Name $Name -Value $Value -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -ErrorAction Stop
                Write-Host "Successfully updated variable '$($Name)'." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to update variable: $($_.Exception.Message)"
            }
        }
    }
}

function Remove-AutomationVariable {
    <#
    .SYNOPSIS
        Removes an Automation Account variable. Aliased as 'remvariable'.

    .DESCRIPTION
        Deletes a variable from the Automation Account. This action is irreversible.

    .PARAMETER Name
        The name of the variable to remove.

    .EXAMPLE
        PS C:\> remvariable -Name "OldApiEndpoint"
#>
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Name
    )
    begin {
        if (-not (Get-AzContext)) {
            Write-Warning "No active Azure context. Run Connect-AzAccount."
            Connect-AzAccount -ErrorAction Stop
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("variable '$($Name)'", "Remove")) {
            try {
                Remove-AzAutomationVariable -Name $Name -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -ErrorAction Stop
                Write-Host "Successfully removed variable '$($Name)'." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to remove variable: $($_.Exception.Message)"
            }
        }
    }
}


# --- ALIASES ---
# Common, short aliases for quick command line use.
Set-Alias -Name lsrb -Value Get-AutomationRunbookInfo
Set-Alias -Name lsgrp -Value Get-UserGroupMembership
Set-Alias -Name addgrp -Value Add-UserToGroup
Set-Alias -Name remgrp -Value Remove-UserFromGroup
Set-Alias -Name runrb -Value Invoke-AutomationRunbook
Set-Alias -Name lsdevice -Value Get-IntuneUserDevice
Set-Alias -Name invdevice -Value Invoke-IntuneDeviceAction
Set-Alias -Name lsdevices -Value Get-UserDevices
Set-Alias -Name lsdevacts -Value Get-IntuneDeviceActionStatus
Set-Alias -Name lsap -Value Get-AutopilotDevice
Set-Alias -Name assignapusr -Value Set-AutopilotDeviceUser
Set-Alias -Name rmapuser -Value Remove-AutopilotDeviceUser
Set-Alias -Name lswhook -Value Get-AutomationWebhook
Set-Alias -Name addwhook -Value New-AutomationWebhook
Set-Alias -Name remwhook -Value Remove-AutomationWebhook
Set-Alias -Name lsvars -Value Get-AutomationVariable
Set-Alias -Name addavar -Value New-AutomationVariable
Set-Alias -Name setavar -Value Set-AutomationVariable
Set-Alias -Name remvar -Value Remove-AutomationVariable
Write-Host "Automation Shell tools loaded. Use 'lsrb' and 'runrb'." -ForegroundColor DarkCyan
