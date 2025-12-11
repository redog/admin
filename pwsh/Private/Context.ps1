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

