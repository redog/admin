<#
.SYNOPSIS
  A collection of REPL-friendly functions to interact with Azure Automation.

.DESCRIPTION
  This script provides a lightweight "shell" experience for managing and running
  Azure Automation runbooks directly from the PowerShell command line.

  To use, configure the variables in the CONFIGURATION section and dot-source this
  file in your PowerShell session or profile:
  . C:\path\to\automation_shell_tools.ps1

.NOTES
  Author: Eric Ortego
  Version: 1.0
#>

#requires -Modules Az.Accounts, Az.Automation

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
            $devices | Select-Object DeviceName, Id, OperatingSystem, ComplianceState, ManagedDeviceOwnerType | Format-Table -AutoSize
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
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipelineByPropertyName = $true)]
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

# --- ALIASES ---
# Common, short aliases for quick command line use.
Set-Alias -Name lsrb -Value Get-AutomationRunbookInfo
Set-Alias -Name runrb -Value Invoke-AutomationRunbook
Set-Alias -Name lsdevice -Value Get-IntuneUserDevice
Set-Alias -Name invdevice -Value Invoke-IntuneDeviceAction
Set-Alias -Name lsdevices -Value Get-UserDevices
Write-Host "Automation Shell tools loaded. Use 'lsrb' and 'runrb'." -ForegroundColor DarkCyan

