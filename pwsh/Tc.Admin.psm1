#
# Tc.Admin.psm1 - meta-module

$here   = $PSScriptRoot
$priv   = Join-Path $here 'Private'

# Load shared helpers (context/config)
$ctxFile   = Join-Path $priv 'Context.ps1'
if (Test-Path $ctxFile) { . $ctxFile }

$configFile = Join-Path $priv 'Config.ps1'
if (Test-Path $configFile) { . $configFile }

# --- EXPLICIT ALIAS EXPORTS ---
# Re-declaring these in the root module ensures they are exported to the user session
# regardless of nested module quirks.

# Automation
Set-Alias -Name lsrb -Value Get-AutomationRunbookInfo
Set-Alias -Name runrb -Value Invoke-AutomationRunbook
Set-Alias -Name lsjobs -Value Get-AutomationRunbookJobHistory
Set-Alias -Name tailjob -Value Wait-AutomationJob
Set-Alias -Name lswhook -Value Get-AutomationWebhook
Set-Alias -Name addwhook -Value New-AutomationWebhook
Set-Alias -Name remwhook -Value Remove-AutomationWebhook
Set-Alias -Name lsvars -Value Get-AutomationVariable
Set-Alias -Name addavar -Value New-AutomationVariable
Set-Alias -Name setavar -Value Set-AutomationVariable
Set-Alias -Name remvar -Value Remove-AutomationVariable

# Intune
Set-Alias -Name lsdevice -Value Get-IntuneDevice
Set-Alias -Name lsdevices -Value Get-UserDevices
Set-Alias -Name invwipe -Value Invoke-IntuneDeviceWipe
Set-Alias -Name gdd -Value Get-TcDeviceDetail

# Autopilot
Set-Alias -Name lsap -Value Get-AutopilotDevice
Set-Alias -Name assignapusr -Value Set-AutopilotDeviceUser
Set-Alias -Name rmapuser -Value Remove-AutopilotDeviceUser
Set-Alias -Name rmapd -Value Remove-AutopilotDevice

# Identity
Set-Alias -Name lsgrp -Value Get-UserGroupMembership
Set-Alias -Name addgrp -Value Add-UserToGroup
Set-Alias -Name remgrp -Value Remove-UserFromGroup

# Azure
Set-Alias -Name lsaz -Value Get-AzResourceOverview


function Show-AdminLs {
    <#
    .SYNOPSIS
        Lists all "ls*" shortcuts in this toolkit and their targets.
    #>
    [CmdletBinding()]
    param(
        [string]$Filter
    )

    $commands = Get-Command -Module Tc.Admin* -Name 'ls*' -CommandType Alias,Function |
        Sort-Object Name

    if ($Filter) {
        $commands = $commands | Where-Object Name -like "*$Filter*"
    }

    $commands | ForEach-Object {
        $target = if ($_.CommandType -eq 'Alias') { $_.Definition } else { $_.Name }
        $help   = Get-Help $target -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            Name     = $_.Name
            Target   = $target
            Synopsis = $help.Synopsis
        }
    } | Format-Table -AutoSize
}

function Show-AdminAliases {
    <#
    .SYNOPSIS
        Lists toolkit aliases and their underlying commands.
    #>
    [CmdletBinding()]
    param()

    Get-Command -Module Tc.Admin* -CommandType Alias |
        Sort-Object Name |
        Select-Object Name, Definition, Module |
        Format-Table -AutoSize
}

Set-Alias lsa Show-AdminLs
Set-Alias lsf Show-AdminAliases

#Export-ModuleMember -Function Show-AdminLs, Show-AdminAliases -Alias lsa, lsf
Export-ModuleMember -Function * -Alias *

