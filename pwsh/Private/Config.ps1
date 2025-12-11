# Simple default; can be overridden in $PROFILE before Import-Module
if (-not $Script:AdminConfig) {
    $Script:AdminConfig = [ordered]@{
        AutomationAccountName      = $AutomationAccountName
        AutomationResourceGroup    = $AutomationResourceGroupName
    }
}

function Get-AdminContext {
    [CmdletBinding()]
    param()

    [PSCustomObject]$Script:AdminConfig
}

Export-ModuleMember -Function Get-AdminContext
