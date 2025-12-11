#
# Tc.Admin.psm1 - meta-module

$here   = Split-Path -Parent $PSCommandPath
$mods   = Join-Path $here 'Modules'
$priv   = Join-Path $here 'Private'

# Load shared helpers (context/config)
$ctxFile   = Join-Path $priv 'Context.ps1'
if (Test-Path $ctxFile) { . $ctxFile }

$configFile = Join-Path $priv 'Config.ps1'
if (Test-Path $configFile) { . $configFile }

# Import feature modules (Automation, Intune, Autopilot, Identity, etc.)
Get-ChildItem -Path $mods -Filter '*.psm1' -ErrorAction SilentlyContinue | ForEach-Object {
    Import-Module $_.FullName -DisableNameChecking
}

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

Export-ModuleMember -Function Show-AdminLs, Show-AdminAliases -Alias lsa, lsf
