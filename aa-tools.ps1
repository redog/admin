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

# If the script variables are not set, try to initialize them from the calling scope (e.g., $PROFILE)
if ($null -ne $AutomationAccountName -and -not $Script:AutomationAccountName) {
    $Script:AutomationAccountName = $AutomationAccountName
}
if ($null -ne $AutomationResourceGroupName -and -not $Script:AutomationResourceGroupName) {
    $Script:AutomationResourceGroupName = $AutomationResourceGroupName
}
# --- END CONFIGURATION ---


function Ensure-AzAutomationContext {
    param (
        [switch]$AutoConnect
    )

    $context = Get-AzContext -ErrorAction SilentlyContinue
    if ($null -ne $context) {
        return $true
    }

    Write-Warning "No active Azure context. Run Connect-AzAccount."

    if (-not $AutoConnect.IsPresent) {
        return $false
    }

    try {
        Connect-AzAccount -ErrorAction Stop | Out-Null
        return $true
    }
    catch {
        throw
    }
}

function Ensure-MgGraphContext {
    param (
        [string[]]$Scopes,
        [switch]$AutoConnect
    )

    $context = Get-MgContext -ErrorAction SilentlyContinue
    if ($null -ne $context) {
        return $true
    }

    if ($Scopes -and $Scopes.Count -gt 0) {
        $scopeList = ($Scopes | ForEach-Object { "'$_'" }) -join ", "
        Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph -Scopes $scopeList"
    }
    else {
        Write-Warning "No active Microsoft Graph context. Run Connect-MgGraph to authenticate."
    }

    if (-not $AutoConnect.IsPresent) {
        return $false
    }

    try {
        if ($Scopes -and $Scopes.Count -gt 0) {
            Connect-MgGraph -Scopes $Scopes -ErrorAction Stop | Out-Null
        }
        else {
            Connect-MgGraph -ErrorAction Stop | Out-Null
        }

        return $true
    }
    catch {
        throw
    }
}


function Get-AutomationRunbookInfo {
    <#
    .SYNOPSIS
        Lists runbooks and their parameters. Aliased as 'lsrb'.

    .DESCRIPTION
        Provides a quick way to list all runbooks in the configured Automation Account
        or inspect the parameters of a specific runbook. Emits raw objects suitable for
        further pipeline processing; use -Verbose to surface status messaging.

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
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
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
                Write-Verbose "Retrieving parameters for runbook '$Name'."
                $runbook = Get-AzAutomationRunbook -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -Name $Name -ErrorAction Stop
                if ($runbook.Parameters.Count -eq 0) {
                    Write-Verbose "No parameters found for runbook '$Name'."
                }
                else {
                    $runbook.Parameters.GetEnumerator() | ForEach-Object {
                        [PSCustomObject]@{
                            Name        = $_.Name
                            Type        = $_.Value.Type
                            Mandatory   = $_.Value.IsMandatory
                            Default     = $_.Value.DefaultValue
                        }
                    } | Write-Output
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

function Remove-AutomationModule {
    <#
    .SYNOPSIS
        Deletes a module from the Automation Account. Aliased as 'remmodule'.

    .DESCRIPTION
        Removes a specific module from the Automation Account. This action can affect
        runbooks that depend on the module, so use it with caution.

    .PARAMETER Name
        The name of the module to remove.

    .EXAMPLE
        PS C:\> remmodule -Name "OldModule"
#>
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Name
    )
    begin {
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("module '$($Name)'", "Remove")) {
            try {
                Remove-AzAutomationModule -Name $Name -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -ErrorAction Stop
                Write-Host "Successfully removed module '$($Name)'." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to remove module '$($Name)': $($_.Exception.Message)"
            }
        }
    }
}

function Get-AutomationRunbookRuntime {
    <#
    .SYNOPSIS
        Displays the runtime version for Automation runbooks. Aliased as 'lsrbrt'.

    .DESCRIPTION
        Retrieves the configured runtime (e.g., PowerShell or Python version) for one or
        all runbooks in the configured Automation Account.

    .PARAMETER Name
        The name of a specific runbook to inspect. If omitted, all runbooks are listed.

    .EXAMPLE
        PS C:\> lsrbrt
        Lists the runtime version for all runbooks.

    .EXAMPLE
        PS C:\> lsrbrt -Name "My-PowerShell-Runbook"
        Displays the runtime for a specific runbook.
#>
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $false, Position = 0)]
        [string]$Name
    )

    begin {
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
        }
        if ([string]::IsNullOrWhiteSpace($Script:AutomationAccountName) -or $Script:AutomationAccountName -eq "YourAutomationAccountName") {
            Write-Error "Configuration needed. Please set `$Script:AutomationAccountName and `$Script:AutomationResourceGroupName in the script file."
            return
        }
    }

    process {
        try {
            $splat = @{
                ResourceGroupName     = $Script:AutomationResourceGroupName
                AutomationAccountName = $Script:AutomationAccountName
                ErrorAction           = 'Stop'
            }
            if ($PSBoundParameters.ContainsKey('Name')) {
                $splat['Name'] = $Name
                Write-Verbose "Getting runtime for runbook '$Name'."
            } else {
                Write-Verbose "Getting runtime for all runbooks."
            }

            $runbooks = Get-AzAutomationRunbook @splat

            if ($null -eq $runbooks) {
                Write-Verbose "No runbooks found."
                return
            }

            $runbooks | ForEach-Object {
                [PSCustomObject]@{
                    Name         = $_.Name
                    Type         = $_.RunbookType
                    Runtime      = $_.RuntimeVersion
                }
            } | Write-Output
        }
        catch {
            Write-Error $_.Exception.Message
        }
    }
}

function Set-AutomationRunbookRuntime {
    <#
    .SYNOPSIS
        Updates the runtime version for a specific runbook. Aliased as 'setrbrt'.

    .DESCRIPTION
        Changes the runtime version for a specified runbook. You must provide a valid
        runtime version string supported by Azure Automation for the runbook's type.

    .PARAMETER Name
        The name of the runbook to update.

    .PARAMETER RuntimeVersion
        The new runtime version to set (e.g., "7.2" for PowerShell, "3.10" for Python).

    .EXAMPLE
        PS C:\> setrbrt -Name "My-Posh-Runbook" -RuntimeVersion "7.2"
        Updates the specified runbook to use the PowerShell 7.2 runtime.
#>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param (
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Name,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$RuntimeVersion
    )

    begin {
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
        }
    }

    process {
        if ($PSCmdlet.ShouldProcess("runbook '$($Name)'", "Set Runtime to '$($RuntimeVersion)'")) {
            try {
                Set-AzAutomationRunbook -Name $Name -RuntimeVersion $RuntimeVersion -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -ErrorAction Stop
                Write-Host "Successfully updated runtime for runbook '$($Name)' to '$($RuntimeVersion)'." -ForegroundColor Green
            }
            catch {
                Write-Error "Failed to update runtime for runbook '$($Name)': $($_.Exception.Message)"
            }
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

    if (-not (Ensure-AzAutomationContext -AutoConnect)) {
        return
    }

    if ([string]::IsNullOrWhiteSpace($Script:AutomationAccountName) -or
        $Script:AutomationAccountName -eq "YourAutomationAccountName" -or
        [string]::IsNullOrWhiteSpace($Script:AutomationResourceGroupName)) {
        throw "Configuration needed. Please set `$Script:AutomationAccountName and `$Script:AutomationResourceGroupName in the script file."
    }

    $AutomationAccountName = $Script:AutomationAccountName
    $RGName = $Script:AutomationResourceGroupName

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

        # Wait for the job and display its output
        $job | Wait-AutomationJob

    } catch {
        Write-Error "Failed to start runbook '$RunbookName': $($_.Exception.Message)"
        return
    }
}

function Get-AutomationRunbookJobHistory {
    <#
    .SYNOPSIS
        Retrieves recent automation job executions for inspection or follow-up actions.

    .DESCRIPTION
        Wraps Get-AzAutomationJob using the configured Automation Account context and emits
        lightweight objects focused on job identity, status, and timing. Accepts optional filters
        for runbook name, job status, and start/end time window to keep results targeted and
        pipeline-friendly.

    .PARAMETER RunbookName
        Filters the job history to a specific runbook.

    .PARAMETER Status
        Filters jobs by their last known status (e.g. Completed, Failed, Suspended).

    .PARAMETER StartTime
        Ignores jobs that started before this timestamp.

    .PARAMETER EndTime
        Ignores jobs that started after this timestamp.

    .EXAMPLE
        PS C:\> Get-AutomationRunbookJobHistory -RunbookName "Restart-Service" -Status Failed -StartTime (Get-Date).AddDays(-7)
        Returns failed jobs for the specified runbook in the last week.
    #>
    [CmdletBinding()]
    param(
        [Parameter(ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('Name')]
        [string]$RunbookName,

        [Parameter()]
        [string]$Status,

        [Parameter()]
        [datetime]$StartTime,

        [Parameter()]
        [datetime]$EndTime
    )

    begin {
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
        }

        if ([string]::IsNullOrWhiteSpace($Script:AutomationAccountName) -or
            $Script:AutomationAccountName -eq "YourAutomationAccountName" -or
            [string]::IsNullOrWhiteSpace($Script:AutomationResourceGroupName)) {
            Write-Error "Configuration needed. Please set `$Script:AutomationAccountName and `$Script:AutomationResourceGroupName in the script file."
            return
        }
    }

    process {
        $queryParams = @{
            ResourceGroupName      = $Script:AutomationResourceGroupName
            AutomationAccountName  = $Script:AutomationAccountName
            ErrorAction            = 'Stop'
        }

        if ($PSBoundParameters.ContainsKey('RunbookName')) {
            $queryParams['RunbookName'] = $RunbookName
            Write-Verbose "Filtering jobs for runbook '$RunbookName'."
        }

        if ($PSBoundParameters.ContainsKey('Status')) {
            $queryParams['Status'] = $Status
            Write-Verbose "Filtering jobs with status '$Status'."
        }

        if ($PSBoundParameters.ContainsKey('StartTime')) {
            $queryParams['StartTime'] = $StartTime
            Write-Verbose "Including jobs starting after $StartTime."
        }

        if ($PSBoundParameters.ContainsKey('EndTime')) {
            $queryParams['EndTime'] = $EndTime
            Write-Verbose "Including jobs starting before $EndTime."
        }

        try {
            $jobs = Get-AzAutomationJob @queryParams
        }
        catch {
            Write-Error "Failed to retrieve automation jobs: $($_.Exception.Message)"
            return
        }

        if (-not $jobs) {
            Write-Verbose "No automation jobs matched the provided filters."
            return
        }

        $jobs | ForEach-Object {
            [PSCustomObject]@{
                JobId       = $_.JobId
                RunbookName = $_.RunbookName
                Status      = $_.Status
                StartTime   = $_.StartTime
                EndTime     = $_.EndTime
            }
        } | Write-Output
    }
}

function Get-IntuneUserDevice {
    <#
    .SYNOPSIS
        Lists Intune-managed devices. Aliased as 'lsdevice' and 'lsdevices'.

    .DESCRIPTION
        Queries Microsoft Graph to find all devices enrolled in Intune. If a UserPrincipalName
        is provided, it filters the list to that specific user. The output includes key
        identifiers and compliance status needed for other actions.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to query. If omitted, all
        Intune-managed devices in the tenant are returned.

    .EXAMPLE
        PS C:\> lsdevice "user@domain.com"
        Lists all devices for a specific user.

    .EXAMPLE
        PS C:\> lsdevices
        Lists all Intune-managed devices in the tenant.
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [string]$UserPrincipalName
    )
    begin {
        # Request broader permissions to ensure user lookups and device reads are covered.
        if (-not (Ensure-MgGraphContext -Scopes 'User.Read.All', 'DeviceManagementManagedDevices.Read.All' -AutoConnect)) {
            return
        }
    }
    process {
        try {
            $queryParams = @{
                All = $true # Retrieve all records
                ErrorAction = 'Stop'
            }

            if (-not [string]::IsNullOrWhiteSpace($UserPrincipalName)) {
                Write-Verbose "Finding Intune devices for '$UserPrincipalName'."
                # Validate the user exists first to provide a better error message.
                $user = Get-MgUser -UserId $UserPrincipalName -ErrorAction Stop -Property 'Id'
                $queryParams['Filter'] = "userPrincipalName eq '$($user.UserPrincipalName)'"
            } else {
                Write-Verbose "Finding all Intune devices."
            }

            $devices = Get-MgDeviceManagementManagedDevice @queryParams

            if ($null -eq $devices) {
                if ($UserPrincipalName) {
                    Write-Verbose "No Intune-managed devices found for '$UserPrincipalName'."
                } else {
                    Write-Verbose "No Intune-managed devices found in the tenant."
                }
                return
            }

            # Select a comprehensive set of properties from both original functions
            $devices | Select-Object UserPrincipalName, DeviceName, Id, Manufacturer, Model, SerialNumber, OperatingSystem, ComplianceState, ManagedDeviceOwnerType | Write-Output
        }
        catch {
            # Provide a more specific error message based on the context
            $errorMessage = if ($UserPrincipalName) { "Could not retrieve devices for '$($UserPrincipalName)'" } else { "Could not retrieve devices" }
            Write-Error "$($errorMessage): $($_.Exception.Message)"
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
        if (-not (Ensure-MgGraphContext -Scopes 'DeviceManagementManagedDevices.ReadWrite.All' -AutoConnect)) {
            return
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
        is not available in v1.0. Outputs raw action result objects; use -Verbose for status updates.

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
        if (-not (Ensure-MgGraphContext -Scopes 'DeviceManagementManagedDevices.Read.All' -AutoConnect)) {
            return
        }
    }
    process {
        try {
            Write-Verbose "Fetching action results for device '$DeviceId'."

            # This information is on the device object itself, in the 'deviceActionResults' property.
            # This requires using the 'beta' endpoint.
            $uri = "https://graph.microsoft.com/beta/deviceManagement/managedDevices/$DeviceId`?`$select=deviceName,deviceActionResults"
            $device = Invoke-MgGraphRequest -Method GET -Uri $uri -ErrorAction Stop

            if ($null -eq $device.deviceActionResults) {
                Write-Verbose "No action results found for device ID '$DeviceId'."
                return
            }

            # Format the output for readability, sorting by the most recent
            $device.deviceActionResults |
                Sort-Object lastUpdatedDateTime -Descending |
                Select-Object actionName, actionState, lastUpdatedDateTime |
                Write-Output
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
        Emits raw group membership objects; use -Verbose for progress details.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to query.

    .EXAMPLE
        PS C:\> lsgrp "user@domain.com"
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [string]$UserPrincipalName
    )
    begin {
        if (-not (Ensure-MgGraphContext -Scopes 'User.Read.All', 'GroupMember.Read.All', 'Group.Read.All' -AutoConnect)) {
            return
        }
    }
    process {
        try {
            Write-Verbose "Fetching group memberships for '$UserPrincipalName'."
            # Use -All to ensure all group memberships are retrieved
            $groups = Get-MgUserMemberOf -UserId $UserPrincipalName -All -ErrorAction Stop
            if ($null -eq $groups) {
                Write-Verbose "User '$UserPrincipalName' is not a member of any groups."
                return
            }
            # The output can contain different object types (e.g., directory roles). We only want groups.
            # The '@odata.type' property helps us identify them.
            $groups | Where-Object { $_.AdditionalProperties['@odata.type'] -eq '#microsoft.graph.group' } | Select-Object DisplayName, Id, Description | Write-Output
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
        if (-not (Ensure-MgGraphContext -Scopes 'User.Read.All', 'GroupMember.ReadWrite.All' -AutoConnect)) {
            return
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
        if (-not (Ensure-MgGraphContext -Scopes 'User.Read.All', 'GroupMember.ReadWrite.All' -AutoConnect)) {
            return
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

            if ($PSCmdlet.ShouldProcess("user '$($user.UserPrincipalName)' from group '$($group.DisplayName)'", "Remove Membership")) {
                Write-Host "Removing '$($user.UserPrincipalName)' from group '$($group.DisplayName)'..." -ForegroundColor Yellow
                # The DirectoryObjectId is the user's ID. No need to pre-query membership.
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

function Get-AutomationWebhook {
    <#
    .SYNOPSIS
        Lists webhooks for a specific runbook. Aliased as 'lswebhook'.

    .DESCRIPTION
        Retrieves all webhooks associated with a given runbook in the configured Automation Account.
        Emits webhook objects for further pipeline use; enable -Verbose to view status updates.

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
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
        }
    }
    process {
        try {
            Write-Verbose "Getting webhooks for runbook '$RunbookName'."
            $webhooks = Get-AzAutomationWebhook -RunbookName $RunbookName -ResourceGroupName $Script:AutomationResourceGroupName -AutomationAccountName $Script:AutomationAccountName -ErrorAction Stop
            if ($null -eq $webhooks) {
                Write-Verbose "No webhooks found for runbook '$RunbookName'."
                return
            }
            $webhooks | Select-Object Name, IsEnabled, ExpiryTime, LastModifiedTime | Write-Output
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
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
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
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
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
        Outputs raw variable metadata objects; use -Verbose for progress details.

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
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
        }
    }
    process {
        try {
            $splat = @{
                ResourceGroupName     = $Script:AutomationResourceGroupName
                AutomationAccountName = $Script:AutomationAccountName
            }
            if ($PSBoundParameters.ContainsKey('Name')) {
                Write-Verbose "Getting variable '$Name'."
                $splat['Name'] = $Name
            } else {
                Write-Verbose "Getting all Automation variables."
            }

            $variables = Get-AzAutomationVariable @splat -ErrorAction Stop
            if ($null -eq $variables) {
                Write-Verbose "No variables found."
                return
            }
            $variables | Select-Object Name, Description, IsEncrypted, LastModifiedTime | Write-Output
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
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
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
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
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
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
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

function Get-AutomationModule {
    <#
    .SYNOPSIS
        Lists modules in the Automation Account. Aliased as 'lsmodule'.

    .DESCRIPTION
        Retrieves a list of modules and their versions from the configured Automation Account.
        This is useful for checking which modules are available for your runbooks.

    .PARAMETER Name
        The name of a specific module to retrieve.

    .EXAMPLE
        PS C:\> lsmodule
        Lists all modules in the account.

    .EXAMPLE
        PS C:\> lsmodule -Name "Az.Accounts"
        Gets the details for a specific module.
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false, Position = 0)]
        [string]$Name
    )
    begin {
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
        }
    }
    process {
        try {
            $splat = @{
                ResourceGroupName     = $Script:AutomationResourceGroupName
                AutomationAccountName = $Script:AutomationAccountName
                ErrorAction           = 'Stop'
            }
            if ($PSBoundParameters.ContainsKey('Name')) {
                $splat['Name'] = $Name
                Write-Verbose "Getting module '$Name'."
            } else {
                Write-Verbose "Getting all Automation modules."
            }

            $modules = Get-AzAutomationModule @splat

            if ($null -eq $modules) {
                Write-Verbose "No modules found."
                return
            }

            $modules | Select-Object Name, Version, IsGlobal, CreationTime
        }
        catch {
            Write-Error "An error occurred while fetching modules: $($_.Exception.Message)"
        }
    }
}

function Import-AutomationModule {
    <#
    .SYNOPSIS
        Installs or updates a module from the PowerShell Gallery. Aliased as 'addmodule'.

    .DESCRIPTION
        Creates a new module import job in the Automation Account to install or update
        a module from the PowerShell Gallery. This process runs asynchronously.

    .PARAMETER Name
        The name of the module to install (e.g., "Az.Accounts").

    .PARAMETER Version
        The specific version of the module to install. If omitted, the latest version
        from the gallery will be used.

    .EXAMPLE
        PS C:\> addmodule -Name "ExchangeOnlineManagement"
        Installs the latest version of the ExchangeOnlineManagement module.

    .EXAMPLE
        PS C:\> addmodule -Name "Az.Accounts" -Version "6.9.0"
        Installs a specific version of the Az.Accounts module.
#>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Name,

        [Parameter(Mandatory = $false, Position = 1)]
        [string]$Version
    )
    begin {
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
        }
    }
    process {
        if ($PSCmdlet.ShouldProcess("module '$($Name)'", "Import from PowerShell Gallery")) {
            try {
                $splat = @{
                    Name                  = $Name
                    ResourceGroupName     = $Script:AutomationResourceGroupName
                    AutomationAccountName = $Script:AutomationAccountName
                    ErrorAction           = 'Stop'
                }
                if ($PSBoundParameters.ContainsKey('Version')) {
                    $splat['ModuleVersion'] = $Version
                }

                New-AzAutomationModule @splat

                Write-Host "Successfully started import job for module '$($Name)'." -ForegroundColor Green
                Write-Host "Go to the Automation Account -> Modules to monitor progress." -ForegroundColor Cyan
            }
            catch {
                Write-Error "Failed to start import job for module '$($Name)': $($_.Exception.Message)"
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
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
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


function Show-AutomationJobOutput {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory=$true, ValueFromPipeline=$true)]
        [Microsoft.Azure.Commands.Automation.Model.Job]$Job
    )

    process {
        # This function assumes the job has already completed.
        $RGName = $Job.ResourceGroupName
        $AutomationAccountName = $Job.AutomationAccountName

        # Display final status
        $statusColor = if ($Job.Status -eq "Completed") { "Green" } else { "Red" }
        Write-Host "Runbook finished with status: $($Job.Status)" -ForegroundColor $statusColor

        if ($Job.Status -eq "Failed" -and $Job.Exception) {
            Write-Host "Runbook Exception: $($Job.Exception)" -ForegroundColor Red
        }
        Write-Host ""

        # Define colors for different output streams
        $streamColors = @{
            "Output"  = "White"; "Verbose" = "Cyan"; "Warning" = "Yellow";
            "Error"   = "Red";   "Debug"   = "Magenta";"Progress"= "Gray"
        }

        # Fetch and display outputs for relevant streams
        foreach ($stream in @("Output", "Verbose", "Warning", "Error")) {
            $color = $streamColors[$stream]
            Write-Host "===== $stream Stream =====" -ForegroundColor $color

            try {
                $streamOutput = Get-AzAutomationJobOutput -ResourceGroupName $RGName -AutomationAccountName $AutomationAccountName -Id $Job.JobId -Stream $stream -ErrorAction Stop

                if ($streamOutput) {
                    foreach ($entry in $streamOutput) {
                        try {
                            $record = Get-AzAutomationJobOutputRecord -ResourceGroupName $RGName -AutomationAccountName $AutomationAccountName -JobId $Job.JobId -Id $entry.StreamRecordId -ErrorAction Stop
                            if ($null -ne $record.Value) {
                                $message = if ($stream -eq "Verbose") { $record.Value.Message } else { $record.Value }
                                if ($null -ne $message) { Write-Host $message -ForegroundColor $color }
                            }
                        } catch {
                            Write-Warning "Could not retrieve details for stream record ID $($entry.StreamRecordId): $($_.Exception.Message)"
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
}


function Wait-AutomationJob {
    <#
    .SYNOPSIS
        Follows a running or completed Automation Job and displays its output streams. Aliased as 'tailjob'.

    .DESCRIPTION
        Takes a Job ID, waits for the job to complete if it is still running, and then
        retrieves and prints all output streams (Output, Verbose, Warning, Error).
        This is useful for monitoring a job's progress in real time or reviewing its results.

    .PARAMETER JobId
        The unique identifier (GUID) of the job to follow.

    .EXAMPLE
        PS C:\> tailjob -JobId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        Waits for the specified job to complete and prints its output.

    .EXAMPLE
        PS C:\> lsjobs | Where-Object { $_.Status -eq 'Running' } | Select-Object -First 1 | tailjob
        Finds the most recent running job and tails its output.
#>
    [CmdletBinding()]
    param (
        [Parameter(Mandatory=$true, ValueFromPipelineByPropertyName = $true)]
        [guid]$JobId
    )

    begin {
        if (-not (Ensure-AzAutomationContext -AutoConnect)) {
            return
        }

        if ([string]::IsNullOrWhiteSpace($Script:AutomationAccountName) -or
            $Script:AutomationAccountName -eq "YourAutomationAccountName" -or
            [string]::IsNullOrWhiteSpace($Script:AutomationResourceGroupName)) {
            throw "Configuration needed. Please set `$Script:AutomationAccountName and `$Script:AutomationResourceGroupName in the script file."
        }
    }

    process {
        $RGName = $Script:AutomationResourceGroupName
        $AutomationAccountName = $Script:AutomationAccountName

        Write-Host "Waiting for job '$JobId' to complete..." -ForegroundColor Cyan

        # Wait for job completion
        while ($true) {
            try {
                $job = Get-AzAutomationJob -ResourceGroupName $RGName -AutomationAccountName $AutomationAccountName -Id $JobId -ErrorAction Stop

                if ($job.Status -in @("Completed", "Failed", "Suspended", "Stopped")) {
                    break
                }

                Start-Sleep -Seconds 5
            } catch {
                Write-Error "Failed to get job status for Job ID ${JobId}: $($_.Exception.Message)"
                Start-Sleep -Seconds 15 # Wait longer on error to avoid spamming failed requests
            }
        }

        # Once the job is complete, pass the final job object to the output display function
        $job | Show-AutomationJobOutput
    }
}

# --- ALIASES ---
# Common, short aliases for quick command line use.
Set-Alias -Name lsrb -Value Get-AutomationRunbookInfo
Set-Alias -Name lsrbrt -Value Get-AutomationRunbookRuntime
Set-Alias -Name setrbrt -Value Set-AutomationRunbookRuntime
Set-Alias -Name lsgrp -Value Get-UserGroupMembership
Set-Alias -Name addgrp -Value Add-UserToGroup
Set-Alias -Name remgrp -Value Remove-UserFromGroup
Set-Alias -Name runrb -Value Invoke-AutomationRunbook
Set-Alias -Name lsjobs -Value Get-AutomationRunbookJobHistory
Set-Alias -Name tailjob -Value Wait-AutomationJob
Set-Alias -Name lsdevice -Value Get-IntuneUserDevice
Set-Alias -Name lsdevices -Value Get-IntuneUserDevice # Alias for listing all devices
Set-Alias -Name invdevice -Value Invoke-IntuneDeviceAction
Set-Alias -Name lsdevacts -Value Get-IntuneDeviceActionStatus
Set-Alias -Name lsap -Value Get-AutopilotDevice
Set-Alias -Name assignapusr -Value Set-AutopilotDeviceUser
Set-Alias -Name rmapuser -Value Remove-AutopilotDeviceUser
Set-Alias -Name lswhook -Value Get-AutomationWebhook
Set-Alias -Name addwhook -Value New-AutomationWebhook
Set-Alias -Name rmwhook -Value Remove-AutomationWebhook
Set-Alias -Name lsvar -Value Get-AutomationVariable
Set-Alias -Name addvar -Value New-AutomationVariable
Set-Alias -Name setvar -Value Set-AutomationVariable
Set-Alias -Name rmvar -Value Remove-AutomationVariable

Set-Alias -Name lsmod -Value Get-AutomationModule
Set-Alias -Name addmod -Value Import-AutomationModule
Set-Alias -Name rmmod -Value Remove-AutomationModule
Write-Host "Automation Shell tools loaded. Key commands: lsrb, runrb, lsdevice, lsmod, lsgrp" -ForegroundColor DarkCyan
