<#
.SYNOPSIS
    Generates a Temporary Access Pass (TAP) for a specified user.
.DESCRIPTION
    This runbook connects to Microsoft Graph using the system-assigned managed identity,
    finds a user by their UPN or Object ID, and creates a Temporary Access Pass with
    a specified lifetime and reusability. The TAP value is returned as output.
	Warning: The tenant policy controls the duration of time and will return a Forbidden 
	error if you attempt to exceed it. Can check the limit with the manual slider in the portal.
.PARAMETER UserId
    The User Principal Name (e.g., 'user@domain.com') or the Object ID of the target user.
.PARAMETER LifetimeInMinutes
    The duration in minutes for which the TAP is valid. Defaults to 60 minutes (1 hour).
.PARAMETER IsReusable
    If specified, the TAP can be used multiple times within its lifetime. 
    If not specified (default), the TAP is single-use only.
.EXAMPLE
    # Generate a default (1-hour, single-use) TAP for a user
    .\Generate-UserTAP.ps1 -UserId 'test@contoso.com'
.EXAMPLE
    # Generate a 2-day, reusable TAP for a user
    .\Generate-UserTAP.ps1 -UserId '7b94350d-061e-4d92-a13e-04716b11c0c5' -LifetimeInMinutes 2880 -IsReusable
#>
Param(
    [Parameter(Mandatory = $false)]
    [object]$WebhookData,

    [Parameter(Mandatory = $false)]
    [string]$UserId,

    [Parameter(Mandatory = $false)]
    [int]$LifetimeInMinutes = 120,

    [Parameter(Mandatory = $false)]
    [bool]$IsReusable = $false
)


function Connect-GraphWithMI {
  Connect-AzAccount -Identity -WarningAction Ignore | Out-Null
  $token = (Get-AzAccessToken -ResourceTypeName MSGraph -WarningAction Ignore).Token
  $param = (Get-Command Connect-MgGraph).Parameters['AccessToken']
  if ($param.ParameterType -eq [securestring]) {
    Connect-MgGraph -NoWelcome -AccessToken ($token | ConvertTo-SecureString -AsPlainText -Force) | Out-Null
  } else {
    Connect-MgGraph -NoWelcome -AccessToken $token | Out-Null
  }
}

# Main error handling block
try {
    # --- Handle Webhook Input ---
    if ($WebhookData) {
        Write-Output "Runbook started via Webhook."
        # If the webhook body was used to populate parameters directly, $UserId will already be set.
        # If not, we need to parse the RequestBody.
        if (-not $UserId -and $WebhookData.RequestBody) {
            Write-Output "Parsing parameters from WebhookData.RequestBody."
            $requestBody = $WebhookData.RequestBody | ConvertFrom-Json

            # Extract parameters from the webhook body
            if ($requestBody.PSObject.Properties.Name -contains 'UserId') {
                $UserId = $requestBody.UserId
            }
            if ($requestBody.PSObject.Properties.Name -contains 'LifetimeInMinutes') {
                # Ensure the value is treated as an integer
                $LifetimeInMinutes = [int]$requestBody.LifetimeInMinutes
            }
            if ($requestBody.PSObject.Properties.Name -contains 'IsReusable') {
                # Ensure the value is treated as a boolean
                $IsReusable = [bool]$requestBody.IsReusable
            }
        }
    }

    # Validate that we have a UserId from one of the sources
    if (-not $UserId) {
        throw "A 'UserId' must be provided either as a direct parameter or in the webhook body."
    }
    # --- 1. AUTHENTICATION ---
    Write-Output "Connecting to Microsoft Graph using System Managed Identity..."
    Connect-GraphWithMI
    Write-Output "Successfully connected."

    # --- 2. FIND THE USER ---
    Write-Output "Searching for user: $UserId"
    $user = Get-MgUser -UserId $UserId -ErrorAction Stop
    if (-not $user) {
        throw "User '$UserId' not found."
    }
    Write-Output "Found user: $($user.DisplayName) (ID: $($user.Id))"

    # --- 3. CREATE THE TAP ---
    # The API expects 'isUsableOnce'. This is the logical inverse of our 'IsReusable' parameter.
    $isUsableOnceValue = -not $IsReusable
    Write-Output "Generating TAP with settings: Lifetime=$LifetimeInMinutes mins, IsReusable=$IsReusable"

    $tapBody = @{
        lifetimeInMinutes = $LifetimeInMinutes
        isUsableOnce      = $isUsableOnceValue
    } | ConvertTo-Json

    $tapUri = "https://graph.microsoft.com/v1.0/users/$($user.Id)/authentication/temporaryAccessPassMethods"

    # Use Invoke-MgGraphRequest for direct API interaction
    $tapResult = Invoke-MgGraphRequest -Method POST -Uri $tapUri -Body $tapBody -ContentType "application/json" -ErrorAction Stop

    if ($tapResult -and $tapResult.temporaryAccessPass) {
        $tapValue = $tapResult.temporaryAccessPass
        Write-Output "SUCCESS: TAP generated for $($user.DisplayName)."
        # --- 4. RETURN THE TAP VALUE ---
        # This makes the TAP available as the output of the runbook job
        Write-Output $tapValue
    }
    else {
        throw "TAP generation failed. The API call succeeded but returned an unexpected response."
    }
}
catch {
    # Catch any terminating errors from the 'try' block
    Write-Error "A critical error occurred: $($_.Exception.Message)"

    # Check for a detailed response in the exception object, which is common for Graph API errors
    if ($_.Exception.Response) {
        try {
            # Read the response stream to get the detailed error message
            $streamReader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
            $responseBody = $streamReader.ReadToEnd()
            $streamReader.Close()
            Write-Error ("Underlying API Response Body: " + $responseBody)
        }
        catch {
            # This catch is for the case where reading the stream fails
            Write-Error "Could not read the underlying API response body."
        }
    }
    # Exit with a non-zero code to ensure the Automation job status is marked as 'Failed'
    exit 1
}
finally {
    # This block ensures disconnection happens even if an error occurs
    if (Get-MgContext) {
        Write-Output "Disconnecting from Microsoft Graph."
        Disconnect-MgGraph | Out-Null
    }
}
