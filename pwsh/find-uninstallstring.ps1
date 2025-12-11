<#
.SYNOPSIS
Finds uninstall information for installed programs by searching the registry.
#>
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$DisplayNameLike,

    [Parameter()]
    [switch]$IncludeCurrentUser
)

# Define registry paths where uninstall information is stored
$registryPaths = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' # For 32-bit apps on 64-bit OS
)

if ($IncludeCurrentUser) {
    $registryPaths += 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' # For per-user installs
}

Write-Verbose "Searching for programs with DisplayName like '$DisplayNameLike' in paths:"
$registryPaths | ForEach-Object { Write-Verbose "- $_" }

$foundPrograms = foreach ($path in $registryPaths) {
    # Get registry key properties, ignore errors for keys that might lack the properties
    Get-ItemProperty -Path $path -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like $DisplayNameLike } -ErrorAction SilentlyContinue
}

if ($foundPrograms) {
    Write-Host "Found the following matching programs:" -ForegroundColor Green
    # Select and display the most relevant properties
    $foundPrograms | Select-Object PSChildName, DisplayName, DisplayVersion, Publisher, InstallDate, UninstallString, QuietUninstallString, PSPath | Format-Table -AutoSize
} else {
    Write-Warning "No program found with DisplayName like '$DisplayNameLike' in the searched registry locations."
    Write-Warning "Try broadening the search (e.g., 'IC*', '*Now*') or include -IncludeCurrentUser if it might be a per-user installation."
}
