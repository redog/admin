#Requires -Modules Microsoft.Graph.Authentication, Microsoft.Graph.Reports

<#
.SYNOPSIS
Checks the MFA registration status for a single user.

.DESCRIPTION
This script is designed to be run as an Azure Automation runbook. It connects to
Microsoft Graph using a system-assigned managed identity and checks whether a
user, identified by their User Principal Name (UPN), has completed MFA registration.

The script outputs a boolean value ($true if registered, $false otherwise) and a
human-readable message. This allows it to be used in larger workflows where the
MFA status determines the next action.

.PARAMETER UserPrincipalName
The User Principal Name (UPN) of the user to check. This is a mandatory
parameter.

.OUTPUTS
[bool] - Returns $true if the user is registered for MFA, $false otherwise.

.EXAMPLE
PS C:\> .\Get-UserMfaStatus.ps1 -UserPrincipalName "user@example.com"
Connects to Graph and checks the MFA status for "user@example.com". It will
output a message and a boolean value indicating their status.

.EXAMPLE
PS C:\> $isRegistered = .\Get-UserMfaStatus.ps1 -UserPrincipalName "user@example.com"
PS C:\> if ($isRegistered) { Write-Output "User is ready!" }
The script's boolean output can be captured in a variable for use in other logic.

.NOTES
The Managed Identity running this script requires the 'UserAuthenticationMethod.Read.All', 'AuditLog.Read.All'
permissions in Microsoft Graph to be able to read user MFA registration details.
#>
param(
  [Parameter(Mandatory = $true)]
  [string]$UserPrincipalName,
  [string]$ScheduleName
)

# Get Automation account details from environment variables for self-management
$automationAccountName = (Get-AutomationVariable -Name 'AutomationAccountName' -ErrorAction Stop)
$resourceGroupName = (Get-AutomationVariable -Name 'AutomationResourceGroupName' -ErrorAction Stop)

# Use System-Assigned Managed Identity to connect to Microsoft Graph
# We need both Az and MgGraph contexts for this script now
try {
    Connect-AzAccount -Identity | Out-Null
    Connect-MgGraph -Identity -NoWelcome | Out-Null
    Write-Output "Successfully connected to Azure and Microsoft Graph."
} catch {
    Write-Error "CRITICAL: Failed to authenticate using Managed Identity. Error: $($_.Exception.Message)"
    throw
}

Write-Output "Checking MFA status for '$UserPrincipalName'..."

# Get the user object to validate existence and get their ID
$user = Get-MgUser -UserId $UserPrincipalName -ErrorAction SilentlyContinue
if (-not $user) {
  Write-Error "User not found: $UserPrincipalName"
  exit 1
}

Write-Output "Found user: $($user.DisplayName) [$($user.Id)]"

# Check the user's MFA registration status.
$isMfaRegistered = $false
try {
    # The report only returns users who have registered at least one method.
    # We specifically check the 'isMfaRegistered' property for a definitive status.
    $mfaStatus = Get-MgReportAuthenticationMethodUserRegistrationDetail -UserRegistrationDetailsId $user.Id -ErrorAction Stop
    if ($mfaStatus -and $mfaStatus.IsMfaRegistered) {
        $isMfaRegistered = $true
    }
}
catch {
    # Handle specific API errors
    $errorMessage = $_.Exception.Message
    if ($errorMessage -like "*Request_ResourceNotFound*") {
        # This is expected if the user has never registered any auth methods.
        # The report entry for them simply doesn't exist.
        Write-Output "User authentication method details not found; assuming not registered for MFA."
        $isMfaRegistered = $false
    }
    elseif (($errorMessage -like "*Authorization_RequestDenied*") -or ($errorMessage -like "*Authentication_MSGraphPermissionMissing*")) {
        # This indicates a permissions issue with the Managed Identity.
        $identity = Get-MgContext
        $identityInfo = "TenantId: $($identity.TenantId), AppId: $($identity.ClientId)"
        Write-Error "Permission Denied. The Managed Identity requires 'UserAuthenticationMethod.Read.All' and 'AuditLog.Read.All' MS Graph permissions. Identity details: $identityInfo"
        exit 1
    }
    else {
        # Handle other, unexpected OData errors
        Write-Error "An unexpected API error occurred: $errorMessage"
        exit 1
    }
}

if ($isMfaRegistered) {
    Write-Output "MFA status for '$UserPrincipalName': Registered. ✅"

    # --- Start removal from onboarding group ---
    $runbookName = "Remove-FromOnboardingGroup"
    Write-Output "User is registered. Starting job to run '$runbookName' for '$UserPrincipalName'."
    try {
        $job = Start-AzAutomationRunbook -ResourceGroupName $resourceGroupName `
            -AutomationAccountName $automationAccountName `
            -Name $runbookName `
            -Parameters @{ UserPrincipalName = $UserPrincipalName } `
            -ErrorAction Stop
        Write-Output "Successfully started job '$($job.JobId)' to remove user from onboarding group."
    } catch {
        # If this fails, we should not proceed to delete the schedule, so the error is re-thrown.
        Write-Error "Failed to start runbook '$runbookName'. Error: $($_.Exception.Message)"
        throw
    }

    # --- Self-delete the schedule if its name was passed in ---
    if (-not [string]::IsNullOrWhiteSpace($ScheduleName)) {
        Write-Output "Attempting to remove schedule '$ScheduleName'..."
        try {
            # Unregister the scheduled runbook first
            Unregister-AzAutomationScheduledRunbook -ResourceGroupName $resourceGroupName `
                -AutomationAccountName $automationAccountName `
                -RunbookName "Get-UserMfaStatus" `
                -ScheduleName $ScheduleName `
                -Confirm:$false `
                -Force `
                -ErrorAction Stop
            Write-Output "Successfully unregistered runbook from schedule '$ScheduleName'."

            # Now delete the schedule itself
            Remove-AzAutomationSchedule -ResourceGroupName $resourceGroupName `
                -AutomationAccountName $automationAccountName `
                -Name $ScheduleName `
                -Confirm:$false `
                -Force `
                -ErrorAction Stop
            Write-Output "Successfully deleted schedule '$ScheduleName'. ✅"
        } catch {
            # This is not a critical failure. The main goal was achieved.
            # The schedule will eventually expire on its own.
            Write-Warning "Could not remove schedule '$ScheduleName'. It will expire naturally. Error: $($_.Exception.Message)"
        }
    } else {
        Write-Output "No ScheduleName provided. Skipping schedule removal."
    }
} else {
    Write-Output "MFA status for '$UserPrincipalName': Not Registered. ❌"
}

# Return a boolean value for programmatic use
return $isMfaRegistered
