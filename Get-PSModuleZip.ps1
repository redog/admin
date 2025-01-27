function Get-PSModuleZip {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$PackageName,

        [Parameter(Mandatory = $true)]
        [string]$PackageVersion
    )

    $tempModulePath = "/tmp/ModuleUpdate_$PackageName"

    if (!(Test-Path -Path $tempModulePath)) {
        New-Item -ItemType Directory -Path $tempModulePath -Force
    }

    try {
        Save-Module -Name $PackageName -Path $tempModulePath -RequiredVersion $PackageVersion -Force -Verbose

        # No need to move anything, as we're saving directly to the desired location.
    }
    catch {
        Write-Error "An error occurred while saving the module: $_"
        return # Exit the function if there's an error
    }

    $zipFilePath = "/tmp/$PackageName.zip"
    try {
        Compress-Archive -Path "$tempModulePath/*" -DestinationPath $zipFilePath -Force -Verbose
        Write-Host "Module '$PackageName' version '$PackageVersion' has been downloaded and zipped to '$zipFilePath'"
    }
    catch {
        Write-Error "An error occurred while compressing the module: $_"
    }

    Remove-Item -Path $tempModulePath -Recurse -Force
}
