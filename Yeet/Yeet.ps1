#Requires -Modules Microsoft.PowerShell.Utility, Microsoft.PowerShell.Management
#Requires -Version 5.1

<#
.SYNOPSIS
Manages SSH keys stored in Bitwarden using the Bitwarden CLI (bw).

.DESCRIPTION
This script provides functionality to list, retrieve, and create SSH keys,
storing them securely in Bitwarden. It interacts with the 'bw' command-line tool.

.PARAMETER Command
Specifies the action to perform:
- list:   List available SSH keys stored in Bitwarden, showing expiration status.
- get:    Retrieve a specific SSH key by name, save it locally, and optionally add the public key to authorized_keys.
- create: Generate a new SSH key pair, save it locally, upload it to Bitwarden, and optionally add the public key to authorized_keys.

.PARAMETER KeyName
The name of the SSH key to 'get'. Required when Command is 'get'.

.EXAMPLE
.\Yeet.ps1 list
Lists all SSH keys in Bitwarden.

.EXAMPLE
.\Yeet.ps1 get my-server-key
Retrieves the key named 'my-server-key', saves the private key to ~/.ssh/my-server-key,
and prompts to add the public key to ~/.ssh/authorized_keys.

.EXAMPLE
.\Yeet.ps1 create
Prompts for a key name, generates a new ed25519 key pair, saves it locally,
uploads it to Bitwarden, and prompts to add the public key to ~/.ssh/authorized_keys.

.NOTES
- I've only briefly tested this in a lab.
- Was created by gemini with a prompt "convert this to powershell" and feeding it the source of yeet.sh. 
- Requires the Bitwarden CLI ('bw') version 2025.2.0 or newer to be installed and in the system's PATH.
- Requires ssh-keygen to be installed and in the system's PATH for key generation.
- Assumes the Bitwarden CLI is already logged in and unlocked when running commands other than checking the status itself.
- Permissions for created/retrieved key files are set to grant the current user Full Control and remove inheritance on Windows.
  This approximates the intent of 'chmod 600' but is platform-specific.
- The 'Get-ExpirationInput' function is defined but not currently used by the 'create' command flow in this version.
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('list', 'get', 'create')]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$KeyName
)

# --- Helper Functions ---

# Check if Bitwarden CLI is installed
function Test-BwCliInstalled {
    if (-not (Get-Command bw -ErrorAction SilentlyContinue)) {
        Write-Error "Bitwarden CLI ('bw') is not installed or not found in PATH."
        exit 1
    }
}

# Check if Bitwarden is logged in and unlocked
function Test-IsBitwardenLoggedIn {
    try {
        $statusJson = bw status --raw # Use --raw for potentially faster parsing if unlocked
        $status = $statusJson | ConvertFrom-Json -ErrorAction Stop
        if ($status.status -ne 'unlocked') {
            Write-Error "Bitwarden is not logged in or vault is locked. Please run 'bw login' or 'bw unlock'."
            return $false
        }
        return $true
    }
    catch {
        # Handle cases where bw status fails entirely or JSON parsing fails
         Write-Error "Failed to check Bitwarden status. Is 'bw' installed and configured? Error: $($_.Exception.Message)"
         # Attempting status without --raw as a fallback for locked state potentially
         $statusOutput = bw status 2>&1
         if ($statusOutput -match '"status":"locked"' ) {
             Write-Error "Bitwarden vault is locked. Please run 'bw unlock'."
         } elseif ($statusOutput -match 'You are not logged in.') {
              Write-Error "Bitwarden is not logged in. Please run 'bw login'."
         }
        return $false
    }
}

# Set appropriate file permissions (Windows approximation of chmod 600)
function Set-PrivateKeyPermissions {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )
    try {
        # Reset ACLs to inherit from parent initially to clear tricky ones
        icacls $FilePath /reset /T /C /Q | Out-Null
        # Remove inheritance
        icacls $FilePath /inheritance:r /T /C /Q | Out-Null
         # Grant current user Full Control
        $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        icacls $FilePath /grant "$($currentUser):F" /T /C /Q | Out-Null
        Write-Verbose "Set permissions for '$FilePath' (Removed inheritance, granted '$currentUser' Full Control)."
    }
    catch {
        Write-Warning "Failed to set permissions on '$FilePath'. Manual adjustment might be needed. Error: $($_.Exception.Message)"
    }
}


# List SSH Keys from Bitwarden
function Get-BwSshKeyList {
    if (-not (Test-IsBitwardenLoggedIn)) { exit 1 }

    Write-Host "Available SSH Keys in Bitwarden:"
    Write-Host "--------------------------------"
    try {
        $itemsJson = bw list items --raw # Faster if list is large
        $items = $itemsJson | ConvertFrom-Json -ErrorAction Stop

        $sshKeys = $items | Where-Object { $_.type -eq 5 } # Type 5 is SSH Key

        if (-not $sshKeys) {
            Write-Host "No SSH keys found in Bitwarden."
            return
        }

        foreach ($key in $sshKeys) {
            $keyName = $key.name
            $expires = $key.sshKey.metadata.expires

            if (-not [string]::IsNullOrEmpty($expires)) {
                try {
                    # Attempt to parse the date string
                    $expiryDate = [datetimeoffset]::Parse($expires).UtcDateTime # Use DateTimeOffset for robustness, convert to UTC DateTime
                    $today = (Get-Date).ToUniversalTime().Date # Compare dates only, in UTC
                    $timeSpan = New-TimeSpan -Start $today -End $expiryDate.Date
                    $daysLeft = [Math]::Floor($timeSpan.TotalDays)

                    if ($daysLeft -lt 0) {
                        Write-Host "$keyName (EXPIRED $(-$daysLeft) days ago)" -ForegroundColor Red
                    }
                    elseif ($daysLeft -eq 0) {
                        Write-Host "$keyName (Expires TODAY)" -ForegroundColor Yellow
                    }
                    else {
                        Write-Host "$keyName (Expires in $daysLeft days)"
                    }
                }
                catch {
                    Write-Host "$keyName (Invalid expiration date format: '$expires')" -ForegroundColor Magenta
                }
            }
            else {
                Write-Host "$keyName (No expiration)"
            }
        }
    }
    catch {
        Write-Error "Failed to list or parse Bitwarden items. Error: $($_.Exception.Message)"
        exit 1
    }
}

# Get user input for expiration (Defined, but not used in create flow below)
function Get-ExpirationInput {
    while ($true) {
        Write-Host "Set key expiration:"
        Write-Host "1) 365 days (default)"
        Write-Host "2) Custom days"
        Write-Host "3) Never expire"
        $exp_choice = Read-Host -Prompt "Choose option [1-3]"

        switch ($exp_choice) {
            { $_ -eq '' -or $_ -eq '1' } {
                return (Get-Date).AddDays(365).ToString('yyyy-MM-dd')
            }
            '2' {
                while ($true) {
                    $days = Read-Host -Prompt "Enter number of days (1-3650)"
                    if ($days -match '^\d+$' -and [int]$days -ge 1 -and [int]$days -le 3650) {
                        return (Get-Date).AddDays([int]$days).ToString('yyyy-MM-dd')
                    }
                    else {
                        Write-Warning "Please enter a valid number between 1 and 3650"
                    }
                }
            }
            '3' {
                return $null # Represent no expiration as null or empty string
            }
            default {
                Write-Warning "Invalid option, please try again"
            }
        }
    }
}

# Retrieve a specific SSH key
function Get-BwSshKey {
    param(
        [Parameter(Mandatory = $true)]
        [string]$KeyNameToGet
    )

    if (-not (Test-IsBitwardenLoggedIn)) { exit 1 }

    $sshPath = Join-Path $HOME ".ssh"
    if (-not (Test-Path $sshPath -PathType Container)) {
        New-Item -Path $sshPath -ItemType Directory | Out-Null
        Write-Verbose "Created directory '$sshPath'"
    }

    Write-Verbose "Searching for key '$KeyNameToGet' in Bitwarden..."
    try {
        # It's often faster to filter locally if the vault isn't huge
        $itemsJson = bw list items --raw
        $items = $itemsJson | ConvertFrom-Json -ErrorAction Stop
        $item = $items | Where-Object { $_.type -eq 5 -and $_.name -eq $KeyNameToGet } | Select-Object -First 1

        if (-not $item) {
            Write-Error "Could not find an SSH key named '$KeyNameToGet' in Bitwarden."
            exit 1
        }

        $itemId = $item.id
        Write-Verbose "Found key '$KeyNameToGet' with ID '$itemId'. Fetching details..."

        # Get the full item details
        $itemJson = bw get item $itemId --raw
        $fullItem = $itemJson | ConvertFrom-Json -ErrorAction Stop

        $privateKey = $fullItem.sshKey.privateKey
        $publicKey = $fullItem.sshKey.publicKey
        $expires = $fullItem.sshKey.metadata.expires

        if ([string]::IsNullOrEmpty($privateKey) -or [string]::IsNullOrEmpty($publicKey)) {
            Write-Error "Could not retrieve the private or public key content from Bitwarden item '$KeyNameToGet'."
            exit 1
        }

        # Check Expiration before saving
         if (-not [string]::IsNullOrEmpty($expires)) {
            try {
                $expiryDate = [datetimeoffset]::Parse($expires).UtcDateTime
                $today = (Get-Date).ToUniversalTime().Date
                $timeSpan = New-TimeSpan -Start $today -End $expiryDate.Date
                $daysLeft = [Math]::Floor($timeSpan.TotalDays)

                if ($daysLeft -lt 0) {
                    Write-Warning "This key '$KeyNameToGet' EXPIRED $(-$daysLeft) days ago!"
                } elseif ($daysLeft -eq 0) {
                    Write-Warning "This key '$KeyNameToGet' expires TODAY!"
                } elseif ($daysLeft -le 30) {
                    Write-Warning "This key '$KeyNameToGet' will expire in $daysLeft days."
                }
            } catch {
                 Write-Warning "Could not parse expiration date '$expires' for key '$KeyNameToGet'."
            }
        }

        $keyPath = Join-Path $sshPath $KeyNameToGet
        if (Test-Path $keyPath) {
             Write-Warning "File '$keyPath' already exists. Overwriting."
        }

        # Save private key
        Set-Content -Path $keyPath -Value $privateKey -NoNewline -Encoding UTF8
        Set-PrivateKeyPermissions -FilePath $keyPath
        Write-Host "Private key '$KeyNameToGet' saved to '$keyPath'"

        # Ask to add public key
        $authorizedKeysPath = Join-Path $sshPath "authorized_keys"
        $confirm = Read-Host "Add public key to '$authorizedKeysPath'? (y/n)"
        if ($confirm -eq 'y') {
            try {
                Add-Content -Path $authorizedKeysPath -Value $publicKey -Encoding UTF8
                # Optionally set permissions on authorized_keys as well if needed
                # Set-PrivateKeyPermissions -FilePath $authorizedKeysPath
                Write-Host "Public key added to '$authorizedKeysPath'"
            }
            catch {
                 Write-Error "Failed to add public key to '$authorizedKeysPath'. Error: $($_.Exception.Message)"
            }
        } else {
            Write-Host "Public key not added to '$authorizedKeysPath'."
            Write-Host "Public Key:"
            Write-Host $publicKey
        }

    }
    catch {
        Write-Error "Failed during key retrieval process. Error: $($_.Exception.Message)"
        exit 1
    }
}

# Create a new SSH key and save to Bitwarden
function New-BwSshKey {
     if (-not (Test-IsBitwardenLoggedIn)) { exit 1 }

    $sshPath = Join-Path $HOME ".ssh"
    if (-not (Test-Path $sshPath -PathType Container)) {
        New-Item -Path $sshPath -ItemType Directory | Out-Null
        Write-Verbose "Created directory '$sshPath'"
    }

    # Default key name
    $hostname = [System.Net.Dns]::GetHostName().Split('.')[0] # Short hostname
    $defaultKeyName = "$hostname-$(Get-Date -Format 'yyyy-MM')"
    $keyNameToCreate = Read-Host -Prompt "Enter a name for the new SSH key (default: $defaultKeyName)"
    if ([string]::IsNullOrWhiteSpace($keyNameToCreate)) {
        $keyNameToCreate = $defaultKeyName
    }

    $keyPath = Join-Path $sshPath $keyNameToCreate
    $keyPathPub = "$keyPath.pub"

    if (Test-Path $keyPath) {
        Write-Error "A key file already exists at '$keyPath'. Please choose a different name or remove the existing file."
        exit 1
    }

     # Generate the key using ssh-keygen
    Write-Host "Generating ED25519 key pair..."
    try {
        # Using -q for quiet, -N '' for no passphrase
        ssh-keygen -t ed25519 -f $keyPath -q -N '' -C $keyNameToCreate # Add comment with key name
        if ($LASTEXITCODE -ne 0) {
             throw "ssh-keygen failed with exit code $LASTEXITCODE"
        }
        Write-Verbose "ssh-keygen completed successfully."
    }
    catch {
        Write-Error "SSH key generation failed. Ensure 'ssh-keygen' is installed and in your PATH. Error: $($_.Exception.Message)"
        # Clean up potentially partially created files
        Remove-Item $keyPath -ErrorAction SilentlyContinue
        Remove-Item $keyPathPub -ErrorAction SilentlyContinue
        exit 1
    }

    # Read the generated keys
    $privateKey = Get-Content -Path $keyPath -Raw -Encoding UTF8
    $publicKey = Get-Content -Path $keyPathPub -Raw -Encoding UTF8

    # Set permissions on the local private key file
    Set-PrivateKeyPermissions -FilePath $keyPath

    # --- Prepare Bitwarden Item ---
    Write-Verbose "Preparing item for Bitwarden..."
    try {
        # Get template
        $templateJson = bw get template item --raw
        $itemObject = $templateJson | ConvertFrom-Json -ErrorAction Stop

        # Populate template
        $itemObject.type = 5 # SSH Key type
        $itemObject.name = $keyNameToCreate
        $itemObject.sshKey = @{
            privateKey = $privateKey
            publicKey  = $publicKey
            # The fingerprint isn't strictly necessary in the template for creation
            # but can be added if desired after parsing `ssh-keygen -lf $keyPath`
            metadata = @{} # Initialize metadata if needed (e.g., for expiration)
            # keyFingerprint = $(ssh-keygen -lf $keyPath | Select-String -Pattern 'SHA256:' | ForEach-Object { ($_ -split ' ')[1] }) # Example fingerprint parsing
        }

        # ---->>> NOTE: Expiration Setting <<<----
        # The original script defined a function Get-ExpirationInput but didn't call it here.
        # To add expiration, uncomment and adapt the following lines:
        # $expirationDateString = Get-ExpirationInput
        # if (-not [string]::IsNullOrEmpty($expirationDateString)) {
        #    $itemObject.sshKey.metadata.expires = $expirationDateString
        # }

        # Convert back to JSON and encode for Bitwarden
        $itemJsonForBw = $itemObject | ConvertTo-Json -Depth 5 -Compress # Compress reduces whitespace
        Write-Verbose "JSON prepared: $itemJsonForBw" # Be careful logging potentially sensitive (though template) data in verbose

        # Create the item in Bitwarden
        Write-Host "Saving key '$keyNameToCreate' to Bitwarden..."
        $createOutput = ($itemJsonForBw | bw encode | bw create item) 2>&1
        # Check Bitwarden CLI exit code AND output for success message
        if ($LASTEXITCODE -ne 0 -or $createOutput -match 'Failed|Error') {
             throw "Failed to save the key to Bitwarden. Output: $createOutput"
        }

        Write-Host "SSH key '$keyNameToCreate' created locally at '$keyPath' and saved to Bitwarden."

        # Ask to add public key
        $authorizedKeysPath = Join-Path $sshPath "authorized_keys"
        $confirm = Read-Host "Add public key to '$authorizedKeysPath'? (y/n)"
        if ($confirm -eq 'y') {
             try {
                Add-Content -Path $authorizedKeysPath -Value $publicKey -Encoding UTF8
                 # Set-PrivateKeyPermissions -FilePath $authorizedKeysPath # Optional permissions
                Write-Host "Public key added to '$authorizedKeysPath'"
             }
             catch {
                 Write-Error "Failed to add public key to '$authorizedKeysPath'. Error: $($_.Exception.Message)"
                 # Don't exit, key is still created
             }
        } else {
            Write-Host "Public key not added to '$authorizedKeysPath'."
            Write-Host "Public Key:"
            Write-Host $publicKey
        }

    }
    catch {
        Write-Error "Failed during key creation or Bitwarden save process. Error: $($_.Exception.Message)"
        Write-Warning "The local key files ('$keyPath' and '$keyPathPub') were created but may not be stored in Bitwarden."
        exit 1
    }
}

# --- Main Script Logic ---

# Check prerequisites first
Test-BwCliInstalled
# Login check is performed within each action function

# Execute the command
switch ($Command) {
    'list' {
        Get-BwSshKeyList
    }
    'get' {
        if ([string]::IsNullOrWhiteSpace($KeyName)) {
            Write-Error "The -KeyName parameter is required for the 'get' command."
            # You might want to show help here too
            exit 1
        }
        Get-BwSshKey -KeyNameToGet $KeyName
    }
    'create' {
        New-BwSshKey
    }
    default {
        # This shouldn't be reached due to ValidateSet, but good practice
        Write-Error "Invalid command '$Command'."
        exit 1
    }
}

exit 0 # Success
