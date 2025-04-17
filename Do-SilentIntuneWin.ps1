<#
.SYNOPSIS
    Downloads IntuneWinAppUtil.exe if needed and uses it to wrap a specified
    application installer (.exe, .msi, etc.) into an .intunewin file for Intune deployment.

.DESCRIPTION
    This script automates the process of creating .intunewin packages.
    It first ensures the latest IntuneWinAppUtil.exe from Microsoft's GitHub is available locally
    (downloading it once if necessary into an 'IntuneWinUtil' subfolder).

    It then takes either a local path to an installer file or a URL to download one.
    It prepares temporary source and output directories, runs IntuneWinAppUtil.exe,
    moves the resulting .intunewin file to the desired location, and cleans up all
    temporary files and folders.

.PARAMETER SourceFile
    The full path to the local setup file (e.g., C:\staging\myapp.msi) to be wrapped.
    Use this parameter or -SourceUrl, but not both.

.PARAMETER SourceUrl
    The URL to download the setup file from (e.g., https://example.com/downloads/myapp.exe).
    The script attempts to determine the filename from the URL.
    Use this parameter or -SourceFile, but not both.

.PARAMETER OutputPath
    Optional. The directory where the final .intunewin file should be saved.
    Defaults to the directory where the script is located ($PSScriptRoot).

.PARAMETER OutputName
    Optional. The desired name for the output .intunewin file (without the extension).
    Defaults to the name of the source installer file.

.EXAMPLE
    .\Do-SilentIntuneWin.ps1 -SourceFile "C:\Installers\7z2301-x64.msi"
    # Wraps the local 7zip MSI, saves 7z2301-x64.intunewin in the script's directory.

.EXAMPLE
    .\Do-SilentIntuneWin.ps1 -SourceUrl "https://github.com/microsoft/winget-cli/releases/download/v1.7.10861/Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle" -OutputPath "C:\IntunePackages" -OutputName "Winget-Latest"
    # Downloads the Winget MSIX bundle, wraps it, and saves C:\IntunePackages\Winget-Latest.intunewin

.EXAMPLE
    .\Do-SilentIntuneWin.ps1 -SourceFile "C:\Installers\setup.exe" -Verbose
    # Wraps setup.exe with detailed output messages.

.EXAMPLE
    .\Do-SilentIntuneWin.ps1 -SourceFile "C:\Installers\setup.exe" -WhatIf
    # Shows what actions would be taken without actually performing them.

.NOTES
    Author: Gemini AI & Me
    Date:   2025-04-17
    Requires: PowerShell 5.1 or later. Internet connectivity may be required for downloads.
#>
[CmdletBinding(SupportsShouldProcess = $true, DefaultParameterSetName = 'LocalPath')]
Param(
    [Parameter(Mandatory = $true, Position = 0, ParameterSetName = 'LocalPath', HelpMessage = 'Path to the local setup file (e.g., .exe, .msi).')]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$SourceFile,

    [Parameter(Mandatory = $true, Position = 0, ParameterSetName = 'Url', HelpMessage = 'URL to download the setup file.')]
    [ValidateScript({ $_ -match '^https?://' })]
    [string]$SourceUrl,

    [Parameter(Mandatory = $false, Position = 1, HelpMessage = 'Optional path for the final .intunewin file directory. Defaults to the script directory.')]
    [ValidateScript({ Test-Path $_ -PathType Container })]
    [string]$OutputPath = $PSScriptRoot,

    [Parameter(Mandatory = $false, Position = 2, HelpMessage = 'Optional name for the final .intunewin file (without extension). Defaults to the source filename.')]
    [string]$OutputName
)

# --- Configuration ---
$IntuneWinUtilUrl = "https://github.com/microsoft/Microsoft-Win32-Content-Prep-Tool/raw/master/IntuneWinAppUtil.exe"
$IntuneWinUtilDir = Join-Path $PSScriptRoot "IntuneWinUtil" # Store tool relative to script
$IntuneWinUtilPath = Join-Path $IntuneWinUtilDir "IntuneWinAppUtil.exe"

# --- Ensure IntuneWinAppUtil.exe Exists ---
if (-not (Test-Path $IntuneWinUtilPath)) {
    Write-Verbose "IntuneWinAppUtil.exe not found at '$IntuneWinUtilPath'."
    if ($PSCmdlet.ShouldProcess($IntuneWinUtilUrl, "Download IntuneWinAppUtil.exe to '$IntuneWinUtilDir'")) {
        try {
            # Ensure the target directory exists
            if (-not (Test-Path $IntuneWinUtilDir -PathType Container)) {
                Write-Verbose "Creating directory '$IntuneWinUtilDir'."
                New-Item -Path $IntuneWinUtilDir -ItemType Directory -Force -ErrorAction Stop | Out-Null
            }
            Write-Host "Downloading IntuneWinAppUtil.exe from '$IntuneWinUtilUrl'..." -ForegroundColor Yellow
            # Use TLS 1.2+
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $IntuneWinUtilUrl -OutFile $IntuneWinUtilPath -UseBasicParsing -ErrorAction Stop
            Write-Host "Successfully downloaded IntuneWinAppUtil.exe to '$IntuneWinUtilPath'." -ForegroundColor Green
        }
        catch {
            Write-Error "Failed to download IntuneWinAppUtil.exe: $($_.Exception.Message)"
            Write-Error "Please download it manually from '$IntuneWinUtilUrl' and place it in '$IntuneWinUtilDir'."
            Exit 1 # Critical failure
        }
    }
    else {
        Write-Warning "Download of IntuneWinAppUtil.exe skipped due to -WhatIf or user cancellation."
        Write-Error "Script cannot proceed without IntuneWinAppUtil.exe."
        Exit 1 # Cannot proceed
    }
}
else {
    Write-Verbose "IntuneWinAppUtil.exe found at '$IntuneWinUtilPath'."
}

# --- Prepare Temporary Environment ---
$tempBase = Join-Path $env:TEMP "IntuneWinWrap_$(Get-Random -Maximum 99999)"
$tempSourceDir = Join-Path $tempBase "Source"
$tempOutputDir = Join-Path $tempBase "Output"
$setupFilePathInTemp = "" # Will hold the path to the installer inside $tempSourceDir
$originalSetupFileName = "" # Just the filename (e.g., setup.exe)

# Use a try/finally block to ensure cleanup happens
try {
    # Create directories if we are actually running (not -WhatIf for this prep step)
    Write-Verbose "Creating temporary directories..."
    New-Item -Path $tempSourceDir -ItemType Directory -Force -ErrorAction Stop | Out-Null
    New-Item -Path $tempOutputDir -ItemType Directory -Force -ErrorAction Stop | Out-Null
    Write-Verbose " Temp Source: $tempSourceDir"
    Write-Verbose " Temp Output: $tempOutputDir"

    # --- Handle Input Application ---
    if ($PSCmdlet.ParameterSetName -eq 'Url') {
        try {
            # Try to get a reasonable filename from the URL
            $uri = [System.Uri]$SourceUrl
            $originalSetupFileName = [System.IO.Path]::GetFileName($uri.LocalPath)
            if ([string]::IsNullOrWhiteSpace($originalSetupFileName)) { $originalSetupFileName = "downloaded_installer_$(Get-Random -Maximum 99999)" } # Fallback

            $setupFilePathInTemp = Join-Path $tempSourceDir $originalSetupFileName
            Write-Verbose "Input is URL. Target temporary path: '$setupFilePathInTemp'"

            if ($PSCmdlet.ShouldProcess($SourceUrl, "Download Source Application to '$setupFilePathInTemp'")) {
                Write-Host "Downloading source application from '$SourceUrl'..." -ForegroundColor Yellow
                # Use TLS 1.2+
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -Uri $SourceUrl -OutFile $setupFilePathInTemp -UseBasicParsing -ErrorAction Stop
                Write-Host "Successfully downloaded source application." -ForegroundColor Green
            }
            else {
                Write-Warning "Download of source application skipped due to -WhatIf or user cancellation."
                # Cannot proceed if source isn't acquired
                Throw "Source application download skipped." # Throw to trigger finally cleanup and exit
            }
        }
        catch {
            Write-Error "Failed to download source application from URL '$SourceUrl': $($_.Exception.Message)"
            Throw # Rethrow to trigger finally cleanup and exit
        }
    }
    else { # ParameterSetName 'LocalPath'
        $originalSetupFileName = [System.IO.Path]::GetFileName($SourceFile)
        $setupFilePathInTemp = Join-Path $tempSourceDir $originalSetupFileName
        Write-Verbose "Input is local path: '$SourceFile'. Target temporary path: '$setupFilePathInTemp'"

        if ($PSCmdlet.ShouldProcess($SourceFile, "Copy Source Application to '$setupFilePathInTemp'")) {
            Write-Verbose "Copying '$SourceFile' to temporary source directory..."
            try {
                Copy-Item -Path $SourceFile -Destination $setupFilePathInTemp -Force -ErrorAction Stop
                Write-Verbose "Source application copied successfully."
            }
            catch {
                Write-Error "Failed to copy source file '$SourceFile' to temporary directory: $($_.Exception.Message)"
                Throw # Rethrow to trigger finally cleanup and exit
            }
        }
        else {
            Write-Warning "Copy of source application skipped due to -WhatIf or user cancellation."
            # Cannot proceed if source isn't acquired
            Throw "Source application copy skipped." # Throw to trigger finally cleanup and exit
        }
    }

    # --- Determine Final Output File Path ---
    if ([string]::IsNullOrWhiteSpace($OutputName)) {
        $OutputName = [System.IO.Path]::GetFileNameWithoutExtension($originalSetupFileName)
        Write-Verbose "OutputName not specified, defaulting to '$OutputName'."
    }
    # Ensure OutputPath exists if specified and different from PSScriptRoot (PSScriptRoot is assumed valid)
    if ($OutputPath -ne $PSScriptRoot -and (-not(Test-Path $OutputPath -PathType Container))) {
         Write-Warning "Specified OutputPath '$OutputPath' does not exist. Attempting to create."
         if($PSCmdlet.ShouldProcess($OutputPath, "Create Output Directory")) {
             try {
                 New-Item -Path $OutputPath -ItemType Directory -Force -ErrorAction Stop | Out-Null
                 Write-Verbose "Created output directory '$OutputPath'."
             } catch {
                 Write-Error "Failed to create output directory '$OutputPath': $($_.Exception.Message)"
                 Throw # Rethrow to trigger finally cleanup and exit
             }
         } else {
            Write-Warning "Creation of output directory skipped due to -WhatIf or user cancellation."
            Throw "Output directory creation skipped." # Throw to trigger finally cleanup and exit
         }
    }

    $finalIntuneWinFile = Join-Path $OutputPath "$($OutputName).intunewin"
    Write-Verbose "Final output file will be: '$finalIntuneWinFile'"

    # --- Run IntuneWinAppUtil.exe ---
    $intuneArgs = @(
        "-c", "`"$tempSourceDir`"" # Source folder
        "-s", "`"$originalSetupFileName`"" # Setup file relative to source folder
        "-o", "`"$tempOutputDir`"" # Output folder for the .intunewin file
        "-q" # Quiet mode - suppresses tool's console output, relies on exit code
    )

    $commandString = "& `"$IntuneWinUtilPath`" $($intuneArgs -join ' ')"
    Write-Verbose "Executing IntuneWinAppUtil: $commandString"

    if ($PSCmdlet.ShouldProcess($setupFilePathInTemp, "Wrap Application using IntuneWinAppUtil.exe")) {
        Write-Host "Starting application wrapping process..." -ForegroundColor Cyan
        try {
            # Start-Process is generally preferred for external executables
            $process = Start-Process -FilePath $IntuneWinUtilPath -ArgumentList $intuneArgs -Wait -NoNewWindow -PassThru -ErrorAction Stop

            if ($process.ExitCode -ne 0) {
                Throw "IntuneWinAppUtil.exe failed with exit code $($process.ExitCode). Check the tool's logs if available (usually in %TEMP%)."
            }
            Write-Host "Application wrapped successfully by the tool." -ForegroundColor Green

            # --- Move Final File ---
            # Find the generated file (tool should create only one .intunewin)
            $generatedFile = Get-ChildItem -Path $tempOutputDir -Filter "*.intunewin" -ErrorAction SilentlyContinue | Select-Object -First 1

            if (-not $generatedFile) {
                Throw "Could not find the generated .intunewin file in the temporary output directory '$tempOutputDir'."
            }

            Write-Verbose "Moving '$($generatedFile.FullName)' to '$finalIntuneWinFile'"
            Move-Item -Path $generatedFile.FullName -Destination $finalIntuneWinFile -Force -ErrorAction Stop
            Write-Host "Successfully created IntuneWin package: '$finalIntuneWinFile'" -ForegroundColor Green

        }
        catch {
            Write-Error "An error occurred during wrapping or moving the file: $($_.Exception.Message)"
            Throw # Rethrow to trigger finally cleanup and exit
        }
    }
    else {
        Write-Warning "Wrapping process skipped due to -WhatIf or user cancellation."
        # No file generated, nothing more to do besides cleanup
    }

}
catch {
    # Errors should have been written already by the code that threw them.
    # Indicate script failure. The finally block will still execute.
    Write-Error "Script execution failed."
    # We need to exit with a non-zero code after cleanup
    $host.SetShouldExit(1)
}
finally {
    # --- Cleanup ---
    Write-Verbose "Starting cleanup of temporary files/folders..."
    if (Test-Path $tempBase -PathType Container) {
        if ($PSCmdlet.ShouldProcess($tempBase, "Remove Temporary Directory")) {
            Write-Verbose "Removing temporary base directory: '$tempBase'"
            Remove-Item -Path $tempBase -Recurse -Force -ErrorAction SilentlyContinue
            Write-Verbose "Cleanup complete."
        } else {
             Write-Warning "Cleanup of '$tempBase' skipped due to -WhatIf or user cancellation."
        }
    } else {
         Write-Verbose "Temporary base directory '$tempBase' not found or already removed."
    }
}

Write-Verbose "Script finished."
# Exit code will be 0 unless $host.SetShouldExit(1) was called in the catch block
