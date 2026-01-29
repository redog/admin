function Backup-BitwardenVault {
    <#
    .SYNOPSIS
        Exports the Bitwarden vault to JSON, encrypts it using Encrypt-File, 
        and securely deletes the plaintext original.

	Example: . ./Encrypt-File.ps1
		 $pass = Read-Host "Enter Password" -AsSecureString
		 . ./Backup-BitwardenVault.ps1
		 bw login && bw unlock
                 Backup-BitwardenVault -DestinationPath .\ -Password $pass
    #>
    [CmdletBinding()]
    param(
        [Parameter(Position=0)]
        [string]$DestinationPath = "$HOME\Documents\BitwardenBackups",

        [Parameter(Mandatory=$true)]
        [System.Security.SecureString]$Password
    )

    # 1. Dependency Check
    if (-not (Get-Command "Encrypt-File" -ErrorAction SilentlyContinue)) {
        Write-Error "Dependency Missing: The 'Encrypt-File' function is not loaded. Please define it first."
        return
    }

    # 2. Check BW Status (Rudimentary check for session var)
    if (-not $env:BW_SESSION) {
        Write-Warning "BW_SESSION is not set. The export command might prompt for a master password or fail."
    }

    # 3. Prepare Directory
    if (-not (Test-Path $DestinationPath)) {
        Write-Verbose "Creating backup directory: $DestinationPath"
        New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null
    }

    $Timestamp = Get-Date -Format "yyyy-MM-dd_HHmm"
    $TempFile  = Join-Path -Path $DestinationPath -ChildPath "bw_export_${Timestamp}.json"

    Write-Progress -Activity "Bitwarden Backup" -Status "Exporting Vault..."
    
    try {
        # 4. Export (Suppressing stdout, capturing stderr if needed)
        # We use --output to let bw handle the file write
        $ExportProcess = Start-Process -FilePath "bw" -ArgumentList "export --format json --output `"$TempFile`"" -PassThru -NoNewWindow -Wait
        
        if ($ExportProcess.ExitCode -ne 0) {
            Write-Error "Bitwarden export failed (Exit Code: $($ExportProcess.ExitCode)). Check if your vault is unlocked."
            return
        }

        if (Test-Path $TempFile) {
            Write-Progress -Activity "Bitwarden Backup" -Status "Encrypting..."
            
            # 5. Encrypt
            Encrypt-File -Path $TempFile -Password $Password
            
            # 6. Cleanup Plaintext
            Remove-Item -Path $TempFile -Force
            
            Write-Host "Backup Secured: ${TempFile}.aes" -ForegroundColor Green
        }
        else {
            Write-Error "Export file not found. 'bw export' may have failed silently."
        }
    }
    catch {
        Write-Error "An unexpected error occurred: $_"
    }
    finally {
        Write-Progress -Activity "Bitwarden Backup" -Completed
    }
}
