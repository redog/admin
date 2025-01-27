function Get-PSModuleZip {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $true)]
        [string]$PackageName,

        [Parameter(Mandatory = $true)]
        [string]$PackageVersion
    )

    # --- 1. Save the Module Locally (using /tmp) ---
    $tempModulePath = "/tmp/ModuleUpdate/$PackageName" # Version NOT included
    $tempModulePathWithVersion = "/tmp/ModuleUpdate/$PackageName-$PackageVersion"
    if (!(Test-Path -Path $tempModulePathWithVersion)) {
        New-Item -ItemType Directory -Path $tempModulePathWithVersion -Force
    }

    try {
        Save-Module -Name $PackageName -Path $tempModulePathWithVersion -RequiredVersion $PackageVersion -Force -Verbose

        # Get the module directory (where Save-Module actually saved it)
        $moduleDir = Get-ChildItem -Path $tempModulePathWithVersion | Where-Object {$_.PSIsContainer}

        # Move module content to directory without version number
        Move-Item -Path "$tempModulePathWithVersion/$moduleDir" -Destination $tempModulePath -Force
    }
    catch {
        Write-Error "An error occurred while saving the module: $_"
        return # Exit the function if there's an error
    }

    # --- 2. Compress to Zip ---
    $zipFilePath = "/tmp/$PackageName.zip" # Version NOT included in zip file name
    try {
        Compress-Archive -Path "$tempModulePath/*" -DestinationPath $zipFilePath -Force -Verbose
        Write-Host "Module '$PackageName' version '$PackageVersion' has been downloaded and zipped to '$zipFilePath'"
    }
    catch {
        Write-Error "An error occurred while compressing the module: $_"
    }

    # --- Cleanup (Optional) ---
    Remove-Item -Path $tempModulePath -Recurse -Force
    Remove-Item -Path $tempModulePathWithVersion -Recurse -Force
}
