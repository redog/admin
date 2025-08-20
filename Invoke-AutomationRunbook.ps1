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
    $AutomationAccountName = ""
    $RGName = ""

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

# Example usage for two processes
# requires Az.Automation
function Start-Two {
    param (
        [Parameter(Mandatory=$true)]
        [string]$AParameter
    )

    Write-Host "Starting two processes with Parameter: $AParameter..." -ForegroundColor Cyan
    
    # Step 1: Run the first runbook on a hybrid worker
    Write-Host "Step 1: Running first process on $HybridRunner..." -ForegroundColor Yellow
    Invoke-AutomationRunbook -RunbookName "Do-HybridRunbook" -HybridRunner $HybridRunner -Parameters @{
        "MyRunbookParam" = $AParameter
    }

    # Step 2: Lock the user account in Azure
    Write-Host "Step 2: Running process two in Azure..." -ForegroundColor Yellow
    Invoke-AutomationRunbook -RunbookName "Do-AzureRunbook" -Parameters @{
        "MyRunbookParam" = $AParameter
    }
    Write-Host "Two processes completed." -ForegroundColor Green
}
# Connect-AzAccount
# Start-Two -AParameter "Yeethis"
