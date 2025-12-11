#requires -Modules Az.Accounts, Az.ResourceGraph

function Get-AzResourceOverview {
    <#
    .SYNOPSIS
        Quick ls-style view over Azure resources via Resource Graph. Aliased as 'lsaz'.
    #>
    [CmdletBinding()]
    param(
        [string]$Query = 'resources | project name, type, location, resourceGroup'
    )

    try {
        Search-AzGraph -Query $Query -ErrorAction Stop
    }
    catch {
        Write-Error "Failed to query Azure Resource Graph: $($_.Exception.Message)"
    }
}

Set-Alias lsaz Get-AzResourceOverview

Export-ModuleMember -Function Get-AzResourceOverview -Alias lsaz
