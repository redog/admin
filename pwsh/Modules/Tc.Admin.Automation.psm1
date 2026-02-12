#requires -Modules Az.Accounts, Az.Automation


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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
            return
        }

        # Check Environment Variables if Script variables are missing
        $account = if (![string]::IsNullOrWhiteSpace($Script:AutomationAccountName)) {
            $Script:AutomationAccountName
        } else {
            $env:AutomationAccountName
        }

        $rg = if (![string]::IsNullOrWhiteSpace($Script:AutomationResourceGroupName)) {
            $Script:AutomationResourceGroupName
        } else {
            $env:AutomationResourceGroupName
        }

        # Validate configuration
        if ([string]::IsNullOrWhiteSpace($account) -or [string]::IsNullOrWhiteSpace($rg)) {
            Write-Error "Configuration needed. Please set `$env:AutomationAccountName and `$env:AutomationResourceGroupName in your profile, or `$Script: variables in the module."
            return
        }
    }

    process {
        try {
            $params = @{
                ResourceGroupName     = $rg
                AutomationAccountName = $account
            }

            if ($PSCmdlet.ParameterSetName -eq 'List') {
                Get-AzAutomationRunbook @params |
                    Select-Object Name, State, LastModifiedTime, CreationTime
            }
            elseif ($Parameters.IsPresent) {
                Write-Verbose "Retrieving parameters for runbook '$Name'."
                $runbook = Get-AzAutomationRunbook @params -Name $Name -ErrorAction Stop
                if ($runbook.Parameters.Count -eq 0) {
                    Write-Verbose "No parameters found for runbook '$Name'."
                }
                else {
                    $runbook.Parameters.GetEnumerator() | ForEach-Object {
                        [PSCustomObject]@{
                            Name      = $_.Name
                            Type      = $_.Value.Type
                            Mandatory = $_.Value.IsMandatory
                            Default   = $_.Value.DefaultValue
                        }
                    } | Write-Output
                }
            }
            else {
                Get-AzAutomationRunbook @params -Name $Name
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

    if (-not (Test-AzAutomationContext -AutoConnect)) {
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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
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
        if (-not (Test-AzAutomationContext -AutoConnect)) {
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

        # Display final status
        $statusColor = if ($job.Status -eq "Completed") { "Green" } else { "Red" }
        Write-Host "Runbook finished with status: $($job.Status)" -ForegroundColor $statusColor

        if ($job.Status -eq "Failed" -and $job.Exception) {
            Write-Host "Runbook Exception: $($job.Exception)" -ForegroundColor Red
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
                $streamOutput = Get-AzAutomationJobOutput -ResourceGroupName $RGName -AutomationAccountName $AutomationAccountName -Id $job.JobId -Stream $stream -ErrorAction Stop

                if ($streamOutput) {
                    foreach ($entry in $streamOutput) {
                        try {
                            $record = Get-AzAutomationJobOutputRecord -ResourceGroupName $RGName -AutomationAccountName $AutomationAccountName -JobId $job.JobId -Id $entry.StreamRecordId -ErrorAction Stop
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

Export-ModuleMember -Function `
    Get-AutomationRunbookInfo, Invoke-AutomationRunbook, `
    Get-AutomationRunbookJobHistory, Wait-AutomationJob, `
    Get-AutomationWebhook, New-AutomationWebhook, Remove-AutomationWebhook, `
    Get-AutomationVariable, New-AutomationVariable, Set-AutomationVariable, Remove-AutomationVariable `
  -Alias `
    lsrb, runrb, lsjobs, tailjob, `
    lswhook, addwhook, remwhook, `
    lsvars, addavar, setavar, remvar
