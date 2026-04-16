<#
.SYNOPSIS
    Unified endpoint asset inventory for DR planning.

.DESCRIPTION
    Pulls device data from multiple sources and joins them on Azure AD Device ID
    (with serial number as fallback) to produce a single CSV showing which
    management systems see each device. Gaps in coverage are themselves the
    useful output — they tell you where your management is broken.

    Sources:
      - Autopilot       (live, via Microsoft Graph)
      - Intune          (live, via Microsoft Graph)
      - Entra ID        (live, via Microsoft Graph)
      - ScreenConnect   (from CSV export — see notes)
      - MeshCentral     (from CSV export — see notes)

.PARAMETER OutputPath
    Folder where the unified CSV will be written. Defaults to current directory.

.PARAMETER ScreenConnectCsv
    Path to a ScreenConnect session export CSV. Optional.
    To generate: in the ScreenConnect web UI, go to the Access or Support tab,
    select all sessions, then Actions > Export to CSV.

.PARAMETER MeshCentralCsv
    Path to a MeshCentral device export CSV. Optional.
    To generate: use the MeshCentral web UI's "My Devices" > Export feature,
    or meshctrl.js ListDevices --json and convert to CSV.

.PARAMETER SkipGraphConnect
    Skip Connect-MgGraph if you're already connected in the current session.

.PARAMETER IncludeBYODMobile
    By default, iOS/Android devices are filtered out (treated as BYOD noise).
    Set this switch to include them.

.EXAMPLE
    .\Get-UnifiedAssetInventory.ps1 -OutputPath C:\Reports

.EXAMPLE
    .\Get-UnifiedAssetInventory.ps1 `
        -ScreenConnectCsv .\screenconnect_export.csv `
        -MeshCentralCsv .\mesh_export.csv `
        -OutputPath C:\Reports

.NOTES
    Required Graph scopes:
      DeviceManagementServiceConfig.Read.All   (Autopilot)
      DeviceManagementManagedDevices.Read.All  (Intune)
      Device.Read.All                          (Entra)
      User.Read.All                            (resolve user principal names)

    Key design decisions (learned the hard way):
      1. Autopilot's property is AzureActiveDirectoryDeviceId — NOT AzureAdDeviceId.
         Intune uses AzureAdDeviceId. We normalize to a single name internally.
      2. Intune and Autopilot sometimes return '00000000-0000-0000-0000-000000000000'
         as a placeholder for "no AAD ID". We treat that as null.
      3. Entra's physicalIds array does NOT reliably contain the device serial. The
         numeric values in [USER-GID] and similar entries are Group IDs, not serials.
         Don't try to parse serial from Entra — use AAD Device ID as the join key.
      4. Serial normalization strips common OEM junk values ("Default string",
         "To be filled by O.E.M.", etc.) to prevent false matches.
      5. Deleted-user UPNs in Intune come back prefixed with the user's object GUID
         (32 hex chars). We strip that to recover the original UPN.

    Serial is kept as a fallback join key for pre-enrollment Autopilot records and
    for agent-based sources (ScreenConnect, MeshCentral) that don't carry AAD ID,
    but AzureAdDeviceId is authoritative.
#>

[CmdletBinding()]
param(
    [string]$OutputPath = (Get-Location).Path,
    [string]$ScreenConnectCsv,
    [string]$MeshCentralCsv,
    [switch]$SkipGraphConnect,
    [switch]$IncludeBYODMobile
)

#region Helpers ----------------------------------------------------------------

function Write-Step {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $Message" -ForegroundColor Cyan
}

function Normalize-Serial {
    # Serial numbers come in with inconsistent casing, whitespace, and occasional
    # junk values like "Default string" or "To be filled by O.E.M." — normalize
    # those to $null so the join doesn't produce false matches.
    param([string]$Serial)

    if ([string]::IsNullOrWhiteSpace($Serial)) { return $null }

    $s = $Serial.Trim().ToUpperInvariant()

    $junk = @(
        'DEFAULT STRING',
        'TO BE FILLED BY O.E.M.',
        'SYSTEM SERIAL NUMBER',
        'NOT SPECIFIED',
        'NONE',
        '0',
        '123456789',
        'SERIAL NUMBER'
    )
    if ($junk -contains $s) { return $null }

    return $s
}

function Normalize-AADDeviceId {
    # The all-zeros GUID is Intune/Autopilot's placeholder for "no AAD ID". Treat as null.
    param([string]$Id)
    if ([string]::IsNullOrWhiteSpace($Id)) { return $null }
    if ($Id -eq '00000000-0000-0000-0000-000000000000') { return $null }
    return $Id
}

function Clean-Upn {
    # Strip 32-char hex GUID prefix from deleted-user UPN residue.
    # e.g. "23f81b718eca496d933b56b01e3b4140Norma@tonychachere.com" -> "Norma@tonychachere.com"
    param([string]$Upn)
    if ([string]::IsNullOrWhiteSpace($Upn)) { return $null }
    if ($Upn -match '^[0-9a-f]{32}(.+@.+)$') { return $Matches[1] }
    return $Upn
}

function New-Lookup {
    # Wrapper around Group-Object -AsHashTable that guarantees a hashtable return
    # even when the input is empty (Group-Object returns $null in that case).
    param($Collection, [string]$Property)
    $filtered = $Collection | Where-Object { $_.$Property }
    if (-not $filtered) { return @{} }
    $result = $filtered | Group-Object $Property -AsHashTable -AsString
    if (-not $result) { return @{} }
    return $result
}

function Find-Record {
    param($AADKey, $SerialKey, $AADLookup, $SerialLookup)
    if ($AADKey    -and $AADLookup.ContainsKey($AADKey))       { return $AADLookup[$AADKey]    | Select-Object -First 1 }
    if ($SerialKey -and $SerialLookup.ContainsKey($SerialKey)) { return $SerialLookup[$SerialKey] | Select-Object -First 1 }
    return $null
}

function Get-RequiredModule {
    param([string]$Name)
    if (-not (Get-Module -ListAvailable -Name $Name)) {
        Write-Step "Installing module $Name (CurrentUser scope)..."
        Install-Module -Name $Name -Scope CurrentUser -Force -AllowClobber
    }
    Import-Module $Name -ErrorAction Stop
}

#endregion

#region Graph connection ------------------------------------------------------

if (-not $SkipGraphConnect) {
    Get-RequiredModule 'Microsoft.Graph.Authentication'
    Get-RequiredModule 'Microsoft.Graph.DeviceManagement'
    Get-RequiredModule 'Microsoft.Graph.Identity.DirectoryManagement'
    Get-RequiredModule 'Microsoft.Graph.Users'

    $scopes = @(
        'DeviceManagementServiceConfig.Read.All',
        'DeviceManagementManagedDevices.Read.All',
        'Device.Read.All',
        'User.Read.All'
    )

    Write-Step "Connecting to Microsoft Graph..."
    Connect-MgGraph -Scopes $scopes -NoWelcome
}

#endregion

#region Autopilot -------------------------------------------------------------

Write-Step "Pulling Autopilot registered devices..."
$autopilotRaw = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -All

$autopilot = foreach ($d in $autopilotRaw) {
    [pscustomobject]@{
        # NOTE: Autopilot uses AzureActiveDirectoryDeviceId, not AzureAdDeviceId.
        # We normalize to AzureAdDeviceId internally for consistency with Intune/Entra.
        AzureAdDeviceId        = Normalize-AADDeviceId $d.AzureActiveDirectoryDeviceId
        SerialNormalized       = Normalize-Serial $d.SerialNumber
        AP_SerialNumber        = $d.SerialNumber
        AP_Manufacturer        = $d.Manufacturer
        AP_Model               = $d.Model
        AP_GroupTag            = $d.GroupTag
        AP_AssignedUser        = Clean-Upn $d.UserPrincipalName
        AP_EnrollmentState     = $d.EnrollmentState
        AP_LastContactedUtc    = $d.LastContactedDateTime
        AP_ManagedDeviceId     = $d.ManagedDeviceId
    }
}
Write-Host "  Found $($autopilot.Count) Autopilot devices" -ForegroundColor Gray

#endregion

#region Intune ----------------------------------------------------------------

Write-Step "Pulling Intune managed devices..."
$intuneRaw = Get-MgDeviceManagementManagedDevice -All

$intune = foreach ($d in $intuneRaw) {
    [pscustomobject]@{
        AzureAdDeviceId       = Normalize-AADDeviceId $d.AzureAdDeviceId
        SerialNormalized      = Normalize-Serial $d.SerialNumber
        IN_DeviceName         = $d.DeviceName
        IN_SerialNumber       = $d.SerialNumber
        IN_Manufacturer       = $d.Manufacturer
        IN_Model              = $d.Model
        IN_OS                 = $d.OperatingSystem
        IN_OSVersion          = $d.OSVersion
        IN_PrimaryUser        = Clean-Upn $d.UserPrincipalName
        IN_LastSyncUtc        = $d.LastSyncDateTime
        IN_EnrolledUtc        = $d.EnrolledDateTime
        IN_Compliance         = $d.ComplianceState
        IN_Encrypted          = $d.IsEncrypted
        IN_JoinType           = $d.JoinType
        IN_ManagedDeviceId    = $d.Id
    }
}
Write-Host "  Found $($intune.Count) Intune devices" -ForegroundColor Gray

#endregion

#region Entra ID --------------------------------------------------------------

Write-Step "Pulling Entra ID device objects..."
$entraRaw = Get-MgDevice -All

# Note: we do NOT attempt to parse serial from physicalIds. The numeric values
# in entries like [USER-GID]:<guid>:<number> are Group IDs, not serials, and
# relying on them produces false matches. AzureAdDeviceId (from DeviceId) is
# the authoritative join key for Entra.
$entra = foreach ($d in $entraRaw) {
    [pscustomobject]@{
        AzureAdDeviceId     = Normalize-AADDeviceId $d.DeviceId
        SerialNormalized    = $null
        EN_DisplayName      = $d.DisplayName
        EN_OS               = $d.OperatingSystem
        EN_OSVersion        = $d.OperatingSystemVersion
        EN_TrustType        = $d.TrustType
        EN_Enabled          = $d.AccountEnabled
        EN_LastSignInUtc    = $d.ApproximateLastSignInDateTime
        EN_IsCompliant      = $d.IsCompliant
        EN_IsManaged        = $d.IsManaged
    }
}

# Filter out BYOD mobile (iOS/Android registered personally, not company property)
# unless the caller explicitly wants them included.
if (-not $IncludeBYODMobile) {
    $beforeFilter = $entra.Count
    $entra = $entra | Where-Object { $_.EN_OS -notin @('iOS','IPhone','Android','iPadOS') }
    Write-Host "  Filtered out $($beforeFilter - $entra.Count) BYOD mobile devices" -ForegroundColor Gray
}

Write-Host "  Found $($entra.Count) Entra devices" -ForegroundColor Gray

#endregion

#region ScreenConnect ---------------------------------------------------------

$screenconnect = @()
if ($ScreenConnectCsv -and (Test-Path $ScreenConnectCsv)) {
    Write-Step "Loading ScreenConnect export..."
    $scRaw = Import-Csv $ScreenConnectCsv

    # ScreenConnect cloud exports vary by report template. We try a few common
    # column names for serial — if yours differs, edit this section.
    $serialCandidates = @('GuestMachineSerialNumber', 'SerialNumber', 'Serial', 'MachineSerial')
    $nameCandidates   = @('Name', 'SessionName', 'GuestMachineName', 'MachineName')
    $userCandidates   = @('GuestLoggedOnUserName', 'HostConnectedUser', 'LoggedOnUser')

    $serialCol = $scRaw[0].PSObject.Properties.Name | Where-Object { $serialCandidates -contains $_ } | Select-Object -First 1
    $nameCol   = $scRaw[0].PSObject.Properties.Name | Where-Object { $nameCandidates   -contains $_ } | Select-Object -First 1
    $userCol   = $scRaw[0].PSObject.Properties.Name | Where-Object { $userCandidates   -contains $_ } | Select-Object -First 1

    if (-not $serialCol) {
        Write-Warning "Could not auto-detect a serial column in the ScreenConnect CSV. Columns found: $($scRaw[0].PSObject.Properties.Name -join ', ')"
    }

    $screenconnect = foreach ($d in $scRaw) {
        [pscustomobject]@{
            AzureAdDeviceId   = $null   # ScreenConnect doesn't carry AAD ID
            SerialNormalized  = if ($serialCol) { Normalize-Serial $d.$serialCol } else { $null }
            SC_Name           = if ($nameCol)   { $d.$nameCol }   else { $null }
            SC_User           = if ($userCol)   { $d.$userCol }   else { $null }
            SC_LastConnected  = $d.GuestLastActivityTime ?? $d.LastConnectedTime ?? $d.LastActivity
            SC_Online         = $d.GuestConnectedTime ?? $d.Online
        }
    }
    Write-Host "  Found $($screenconnect.Count) ScreenConnect sessions ($(($screenconnect | Where-Object SerialNormalized).Count) with resolvable serials)" -ForegroundColor Gray
} else {
    Write-Step "Skipping ScreenConnect (no CSV provided)"
}

#endregion

#region MeshCentral -----------------------------------------------------------

$mesh = @()
if ($MeshCentralCsv -and (Test-Path $MeshCentralCsv)) {
    Write-Step "Loading MeshCentral export..."
    $mcRaw = Import-Csv $MeshCentralCsv

    $serialCandidates = @('SerialNumber', 'serial', 'bios_serial', 'BiosSerial')
    $nameCandidates   = @('name', 'Name', 'hostname', 'ComputerName')
    $userCandidates   = @('user', 'LoggedInUser', 'users')

    $serialCol = $mcRaw[0].PSObject.Properties.Name | Where-Object { $serialCandidates -contains $_ } | Select-Object -First 1
    $nameCol   = $mcRaw[0].PSObject.Properties.Name | Where-Object { $nameCandidates   -contains $_ } | Select-Object -First 1
    $userCol   = $mcRaw[0].PSObject.Properties.Name | Where-Object { $userCandidates   -contains $_ } | Select-Object -First 1

    $mesh = foreach ($d in $mcRaw) {
        [pscustomobject]@{
            AzureAdDeviceId   = $null   # MeshCentral doesn't carry AAD ID
            SerialNormalized  = if ($serialCol) { Normalize-Serial $d.$serialCol } else { $null }
            MC_Name           = if ($nameCol)   { $d.$nameCol }   else { $null }
            MC_User           = if ($userCol)   { $d.$userCol }   else { $null }
            MC_LastSeen       = $d.lastaddr ?? $d.LastSeen ?? $d.lastconnect
            MC_OS             = $d.osdesc ?? $d.OS
        }
    }
    Write-Host "  Found $($mesh.Count) MeshCentral devices ($(($mesh | Where-Object SerialNormalized).Count) with resolvable serials)" -ForegroundColor Gray
} else {
    Write-Step "Skipping MeshCentral (no CSV provided)"
}

#endregion

#region Join on AAD Device ID (with serial fallback) --------------------------

Write-Step "Joining sources..."

# Build lookup tables on BOTH keys for each source. New-Lookup guarantees a
# hashtable (possibly empty) rather than $null.
$apByAAD    = New-Lookup $autopilot     'AzureAdDeviceId'
$apBySerial = New-Lookup $autopilot     'SerialNormalized'
$inByAAD    = New-Lookup $intune        'AzureAdDeviceId'
$inBySerial = New-Lookup $intune        'SerialNormalized'
$enByAAD    = New-Lookup $entra         'AzureAdDeviceId'
$enBySerial = New-Lookup $entra         'SerialNormalized'   # typically empty
$scByAAD    = New-Lookup $screenconnect 'AzureAdDeviceId'    # typically empty
$scBySerial = New-Lookup $screenconnect 'SerialNormalized'
$mcByAAD    = New-Lookup $mesh          'AzureAdDeviceId'    # typically empty
$mcBySerial = New-Lookup $mesh          'SerialNormalized'

# Build master set of "device identities" — prefer AzureAdDeviceId, fall back to serial
$identities = @{}
foreach ($src in @($autopilot, $intune, $entra, $screenconnect, $mesh)) {
    foreach ($d in $src) {
        $key = if ($d.AzureAdDeviceId) { "AAD:$($d.AzureAdDeviceId)" }
               elseif ($d.SerialNormalized) { "SN:$($d.SerialNormalized)" }
               else { $null }
        if ($key) { $identities[$key] = $true }
    }
}

$unified = foreach ($id in $identities.Keys) {
    $aadKey    = if ($id -like 'AAD:*') { $id.Substring(4) } else { $null }
    $serialKey = if ($id -like 'SN:*')  { $id.Substring(3) } else { $null }

    # For AAD-keyed identities, try to find an associated serial for cross-source
    # matching against agents that don't carry AAD ID (ScreenConnect, MeshCentral)
    if ($aadKey -and -not $serialKey) {
        $candidates = @()
        if ($apByAAD.ContainsKey($aadKey)) { $candidates += $apByAAD[$aadKey] }
        if ($inByAAD.ContainsKey($aadKey)) { $candidates += $inByAAD[$aadKey] }
        $anyMatch = $candidates | Where-Object { $_.SerialNormalized } | Select-Object -First 1
        if ($anyMatch) { $serialKey = $anyMatch.SerialNormalized }
    }

    $ap = Find-Record $aadKey $serialKey $apByAAD $apBySerial
    $in = Find-Record $aadKey $serialKey $inByAAD $inBySerial
    $en = Find-Record $aadKey $serialKey $enByAAD $enBySerial
    $sc = Find-Record $aadKey $serialKey $scByAAD $scBySerial
    $mc = Find-Record $aadKey $serialKey $mcByAAD $mcBySerial

    [pscustomobject]@{
        Serial                = if ($serialKey) { $serialKey } else { '(no serial)' }
        AzureAdDeviceId       = $aadKey

        # Best-guess identity fields (first source that has a value wins)
        DeviceName            = $in.IN_DeviceName ?? $en.EN_DisplayName ?? $sc.SC_Name ?? $mc.MC_Name
        Manufacturer          = $in.IN_Manufacturer ?? $ap.AP_Manufacturer
        Model                 = $in.IN_Model ?? $ap.AP_Model
        OS                    = $in.IN_OS ?? $en.EN_OS ?? $mc.MC_OS
        OSVersion             = $in.IN_OSVersion ?? $en.EN_OSVersion
        AssignedUser          = $in.IN_PrimaryUser ?? $ap.AP_AssignedUser ?? $sc.SC_User ?? $mc.MC_User
        GroupTag              = $ap.AP_GroupTag

        # Coverage flags — these are what DR planning actually cares about
        InAutopilot           = [bool]$ap
        InIntune              = [bool]$in
        InEntra               = [bool]$en
        InScreenConnect       = [bool]$sc
        InMeshCentral         = [bool]$mc
        SourceCount           = @($ap,$in,$en,$sc,$mc | Where-Object { $_ }).Count

        # Freshness / state
        Intune_LastSyncUtc    = $in.IN_LastSyncUtc
        Intune_Compliance     = $in.IN_Compliance
        Intune_Encrypted      = $in.IN_Encrypted
        Entra_TrustType       = $en.EN_TrustType
        Entra_LastSignInUtc   = $en.EN_LastSignInUtc
        Autopilot_EnrollState = $ap.AP_EnrollmentState
        SC_LastConnected      = $sc.SC_LastConnected
        MC_LastSeen           = $mc.MC_LastSeen
    }
}

Write-Host "  Unified records: $($unified.Count)" -ForegroundColor Gray

#endregion

#region Output ----------------------------------------------------------------

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$outFile = Join-Path $OutputPath "AssetInventory-$stamp.csv"
$unified | Sort-Object -Property @{e='SourceCount';desc=$true}, DeviceName |
    Export-Csv -Path $outFile -NoTypeInformation -Encoding UTF8

Write-Step "Wrote $($unified.Count) records to $outFile"

# Summary for the console — this is the leadership-friendly version
Write-Host "`n=== Coverage summary ===" -ForegroundColor Green
$summary = [pscustomobject]@{
    'Total unique devices'        = $unified.Count
    'Fully managed (AP+IN+EN)'    = ($unified | Where-Object { $_.InAutopilot -and $_.InIntune -and $_.InEntra }).Count
    'Cold spares (AP+EN, no IN)'  = ($unified | Where-Object { $_.InAutopilot -and -not $_.InIntune -and $_.InEntra }).Count
    'AP only (pre-enroll)'        = ($unified | Where-Object { $_.InAutopilot -and -not $_.InIntune -and -not $_.InEntra }).Count
    'IN only (non-AP enrolled)'   = ($unified | Where-Object { -not $_.InAutopilot -and $_.InIntune -and -not $_.InEntra }).Count
    'EN only (orphan records)'    = ($unified | Where-Object { -not $_.InAutopilot -and -not $_.InIntune -and $_.InEntra }).Count
    'Intune not encrypted'        = ($unified | Where-Object { $_.InIntune -and -not $_.Intune_Encrypted }).Count
    'Intune non-compliant'        = ($unified | Where-Object { $_.InIntune -and $_.Intune_Compliance -ne 'compliant' }).Count
}
$summary | Format-List

#endregion
