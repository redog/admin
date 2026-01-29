#requires -Modules Microsoft.Graph.Identity.DirectoryManagement, Microsoft.Graph.DeviceManagement.Enrollment, Microsoft.Graph.DeviceManagement.Actions, Microsoft.Graph.DeviceManagement
#region: Globals
$global:IsConnected = $false
#endregion: Globals

#region: Connection
function Connect-Graph {
    if (-not $global:IsConnected) {
        Write-Host "Connecting to Microsoft Graph..."
        try {
            # Connect to Microsoft Graph with necessary permissions
            Connect-MgGraph -Scopes "Device.Read.All", "Device.ReadWrite.All", "User.Read.All", "DeviceManagementServiceConfig.ReadWrite.All", "DeviceManagementManagedDevices.ReadWrite.All", "DeviceManagementManagedDevices.PrivilegedOperations.All"
            $global:IsConnected = $true
            Write-Host "Successfully connected to Microsoft Graph." -ForegroundColor Green
        }
        catch {
            Write-Host "Failed to connect to Microsoft Graph. Please check your permissions and try again." -ForegroundColor Red
            $global:IsConnected = $false
        } }
    else {
        Write-Host "Already connected to Microsoft Graph."
    }
}
#endregion: Connection

#region: Commands
function Show-Help {
    Write-Host @"
Available commands:
  lsed         - List Entra devices
  lsapd        - List Autopilot devices
  auapd        - Assign user to Autopilot device
  rmuapd       - Remove user from Autopilot device
  lsitd        - List Intune devices
  rwitd        - Remote wipe Intune device
  rmapd        - Remove/delete Autopilot device
  gdd          - Get device details (Entra, Intune, and Autopilot)
  sid          - Sync Intune device
  ritd <name>  - Retire Intune device
  help         - Show this help message
  cls          - Clear the screen
  exit         - Exit the tool

Note: For commands that take arguments, you can provide them on the command line (e.g., 'gdd 12345') or run the command without arguments to be prompted.
"@
}

function Get-AutopilotDeviceBySerial {
  param([Parameter(Mandatory=$true)][string]$Serial)

  # Use server-side 'contains' first (empirically reliable), then narrow.
  $candidates = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -Filter "contains(serialNumber, '$Serial')" -ErrorAction Stop

  if(-not $candidates){
    # Fallback: client-side search across all if the filter behaves oddly
    $all = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -All -PageSize 200 -ErrorAction Stop
    $candidates = $all | Where-Object { $_.serialNumber -like "*$Serial*" }
  }

  if(-not $candidates){ throw "No Autopilot devices found matching serial '$Serial'." }

  # Prefer exact match if present
  $exact = $candidates | Where-Object { $_.serialNumber -eq $Serial }
  if($exact){ $candidates = $exact }

  $arr = @($candidates)
  if($arr.Count -gt 1){
    $list = $arr | Select-Object serialNumber, id, orderIdentifier, managedDeviceId | Format-Table -AutoSize | Out-String
    throw "Multiple Autopilot devices matched '$Serial'. Narrow it down:`n$list"
  }

  return $arr[0]
}

function Get-UserByUpn {
  param([Parameter(Mandatory=$true)][string]$Upn)
  try {
    return Get-MgUser -UserId $Upn -Property Id,DisplayName,UserPrincipalName
  } catch {
    $u = Get-MgUser -Filter "userPrincipalName eq '$Upn'" -Property Id,DisplayName,UserPrincipalName
    if(-not $u){ throw "User '$Upn' not found." }
    return $u
  }
}

function Assign-UserToAutopilotDevice {
  param(
    [Parameter(Mandatory=$true)]$DeviceSerial,
    [Parameter(Mandatory=$true)]$UserPrincipalName
  )
  $device = Get-AutopilotDeviceBySerial -Serial $DeviceSerial
  $deviceId = $ApDevice.Id
  $user = Get-UserByUPN $UserPrincipalName
  $upn = $user.UserPrincipalName

  if($PSCmdlet.ShouldProcess("AutopilotId=$deviceId","Assign user '$($user.DisplayName)' <$upn>")){
    $updateParams = @{
      WindowsAutopilotDeviceIdentityId = $deviceId
      UserPrincipalName                = $upn
      AddressableUsername              = $user.DisplayName
    }
    Update-MgDeviceManagementWindowsAutopilotDeviceIdentityDeviceProperty @updateParams | Out-Null
  }
}

function List-EntraDevices {
    try {
        Write-Host "Getting Entra devices..."
        $devices = Get-MgDevice -All
        if ($devices) {
            $devices | Select-Object DisplayName, OperatingSystem, OperatingSystemVersion, ApproximateLastSignInDateTime
        }
        else {
            Write-Host "No Entra devices found." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "An error occurred while getting Entra devices: $_" -ForegroundColor Red
    }
}

function List-IntuneDevices {
    try {
        Write-Host "Getting Intune devices..."
        $devices = Get-MgDeviceManagementManagedDevice -All
        if ($devices) {
            $devices | Select-Object DeviceName, OperatingSystem, ComplianceState, LastSyncDateTime
        }
        else {
            Write-Host "No Intune devices found." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "An error occurred while getting Intune devices: $_" -ForegroundColor Red
    }
}

function List-AutopilotDevices {
    try {
        Write-Host "Getting Autopilot devices..."
        $devices = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -All
        if ($devices) {
            $devices | Select-Object SerialNumber, Manufacturer, Model, PurchaseOrderIdentifier, UserPrincipalName
        }
        else {
            Write-Host "No Autopilot devices found." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "An error occurred while getting Autopilot devices: $_" -ForegroundColor Red
    }
}

function Assign-UserToAutopilotDevice {
    param(
        [string]$SerialNumber,
        [string]$UserPrincipalName
    )
    try {
        if ([string]::IsNullOrWhiteSpace($SerialNumber)) {
            $SerialNumber = Read-Host "Enter the serial number of the Autopilot device"
        }
        if ([string]::IsNullOrWhiteSpace($UserPrincipalName)) {
            $UserPrincipalName = Read-Host "Enter the User Principal Name (UPN) to assign"
        }

        if ([string]::IsNullOrWhiteSpace($SerialNumber) -or [string]::IsNullOrWhiteSpace($UserPrincipalName)) {
            Write-Host "Serial number and UPN cannot be empty." -ForegroundColor Yellow
            return
        }

        Write-Host "Finding Autopilot device with serial number '$serialNumber'..."
		$device = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -Filter "contains(serialNumber, '$SerialNumber')" -ErrorAction Stop
        #$device = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -Filter "serialNumber eq '$serialNumber'"

        if (-not $device) {
            Write-Host "Autopilot device with serial number '$serialNumber' not found." -ForegroundColor Yellow
            return
        }
		$updateParams = @{
			WindowsAutopilotDeviceIdenityId = $device.id
			UserPrincipalName = $UserPrincipalName
		}

        Write-Host "Assigning user '$($UserPrincipalName)' to device '$($device.Id)'..."
        Update-MgDeviceManagementWindowsAutopilotDeviceIdentityDeviceProperty @updateParams -ErrorAction Stop | out-null
        Write-Host "Successfully assigned user '$($UserPrincipalName)' to device with serial number '$($SerialNumber)'." -ForegroundColor Green
    }
    catch {
        Write-Host "An error occurred while assigning the user: $_" -ForegroundColor Red
    }
}

function Unassign-UserFromAutopilotDevice {
    param(
        [string]$SerialNumber
    )
    try {
        if ([string]::IsNullOrWhiteSpace($SerialNumber)) {
            $SerialNumber = Read-Host "Enter the serial number of the Autopilot device"
        }

        if ([string]::IsNullOrWhiteSpace($SerialNumber)) {
            Write-Host "Serial number cannot be empty." -ForegroundColor Yellow
            return
        }

        Write-Host "Finding Autopilot device with serial number '$serialNumber'..."
        $device = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -Filter "serialNumber eq '$serialNumber'"

        if (-not $device) {
            Write-Host "Autopilot device with serial number '$serialNumber' not found." -ForegroundColor Yellow
            return
        }

        Write-Host "Unassigning user from device '$($device.Id)'..."
        Update-MgDeviceManagementWindowsAutopilotDeviceIdentity -WindowsAutopilotDeviceIdentityId $device.Id -UserPrincipalName "" -AddressableUserName ""
        Write-Host "Successfully unassigned user from device with serial number '$($SerialNumber)'." -ForegroundColor Green
    }
    catch {
        Write-Host "An error occurred while unassigning the user: $_" -ForegroundColor Red
    }
}

function Wipe-IntuneDevice {
    param(
        [string]$DeviceName
    )
    try {
        if ([string]::IsNullOrWhiteSpace($DeviceName)) {
            $DeviceName = Read-Host "Enter the name of the Intune device to wipe"
        }

        if ([string]::IsNullOrWhiteSpace($DeviceName)) {
            Write-Host "Device name cannot be empty." -ForegroundColor Yellow
            return
        }

        Write-Host "Finding Intune device(s) with name '$($DeviceName)'..."
        $devices = Get-MgDeviceManagementManagedDevice -Filter "startswith(deviceName, '$($DeviceName)')"

        $device = $null
        if (-not $devices) {
            Write-Host "No Intune devices found with a name starting with '$($DeviceName)'." -ForegroundColor Yellow
            return
        }
        elseif ($devices.Count -eq 1) {
            $device = $devices
        }
        else {
            Write-Host "Multiple devices found. Please select one:" -ForegroundColor Yellow
            for ($i = 0; $i -lt $devices.Count; $i++) {
                Write-Host "[$($i+1)] $($devices[$i].DeviceName) (User: $($devices[$i].UserPrincipalName), OS: $($devices[$i].OperatingSystem))"
            }
            $selection = Read-Host "Enter the number of the device to wipe"
            if ($selection -match '^\d+$' -and [int]$selection -ge 1 -and [int]$selection -le $devices.Count) {
                $device = $devices[[int]$selection - 1]
            }
            else {
                Write-Host "Invalid selection." -ForegroundColor Red
                return
            }
        }

        $confirmation = Read-Host "Are you sure you want to wipe device '$($device.DeviceName)' (managed by $($device.UserPrincipalName)))? (y/n)"
        if ($confirmation -ne 'y') {
            Write-Host "Wipe operation cancelled."
            return
        }

        $keepEnrollmentData = Read-Host "Keep enrollment data? (y/n)"
        $keepEnrollmentDataBool = if ($keepEnrollmentData -eq 'y') { $true } else { $false }

        Write-Host "Wiping device '$($device.DeviceName)'..."
        Invoke-MgWipeDeviceManagementManagedDevice -ManagedDeviceId $device.Id -KeepEnrollmentData $keepEnrollmentDataBool
        Write-Host "Successfully initiated wipe for device '$($device.DeviceName)'." -ForegroundColor Green
    }
    catch {
        Write-Host "An error occurred while wiping the device: $_" -ForegroundColor Red
    }
}

function Remove-AutopilotDevice {
    param(
        [string]$SerialNumber
    )
    try {
        if ([string]::IsNullOrWhiteSpace($SerialNumber)) {
            $SerialNumber = Read-Host "Enter the serial number of the Autopilot device to remove"
        }

        if ([string]::IsNullOrWhiteSpace($SerialNumber)) {
            Write-Host "Serial number cannot be empty." -ForegroundColor Yellow
            return
        }

        Write-Host "Finding Autopilot device with serial number '$serialNumber'..."
        $device = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -Filter "serialNumber eq '$serialNumber'"

        if (-not $device) {
            Write-Host "Autopilot device with serial number '$serialNumber' not found." -ForegroundColor Yellow
            return
        }

        $confirmation = Read-Host "Are you sure you want to remove Autopilot device with serial number '$($device.SerialNumber)'? (y/n)"
        if ($confirmation -ne 'y') {
            Write-Host "Remove operation cancelled."
            return
        }

        Write-Host "Removing Autopilot device '$($device.Id)'..."
        Remove-MgDeviceManagementWindowsAutopilotDeviceIdentity -WindowsAutopilotDeviceIdentityId $device.Id
        Write-Host "Successfully removed Autopilot device with serial number '$($device.SerialNumber)'." -ForegroundColor Green
    }
    catch {
        Write-Host "An error occurred while removing the Autopilot device: $_" -ForegroundColor Red
    }
}

function Get-DeviceDetails {
    param(
        [string]$SerialNumber
    )
    try {
        if ([string]::IsNullOrWhiteSpace($SerialNumber)) {
            $SerialNumber = Read-Host "Enter the serial number of the device"
        }

        if ([string]::IsNullOrWhiteSpace($SerialNumber)) {
            Write-Host "Serial number cannot be empty." -ForegroundColor Yellow
            return
        }

        Write-Host "Getting device details for serial number '$serialNumber'..."

        $autopilotDevice = Get-MgDeviceManagementWindowsAutopilotDeviceIdentity -Filter "serialNumber eq '$serialNumber'" | Select-Object -First 1
        $intuneDevice = Get-MgDeviceManagementManagedDevice -Filter "serialNumber eq '$serialNumber'" | Select-Object -First 1

        $entraDevice = $null
        $entraDeviceId = $intuneDevice.AzureADDeviceId
        if (-not $entraDeviceId) {
            $entraDeviceId = $autopilotDevice.AzureActiveDirectoryDeviceId
        }
        if ($entraDeviceId) {
            $entraDevice = Get-MgDevice -DeviceId $entraDeviceId
        }

        # --- Display Autopilot Details ---
        Write-Host "`n--- Autopilot Details ---" -ForegroundColor Cyan
        if ($autopilotDevice) {
            $autopilotDevice | Format-List DisplayName, SerialNumber, Manufacturer, Model, UserPrincipalName, EnrollmentState, LastContactedDateTime
        } else {
            Write-Host "No Autopilot device found." -ForegroundColor Yellow
        }

        # --- Display Intune Details ---
        Write-Host "`n--- Intune Details ---" -ForegroundColor Cyan
        if ($intuneDevice) {
            $intuneDevice | Format-List DeviceName, UserPrincipalName, OperatingSystem, ComplianceState, LastSyncDateTime, ManagedDeviceOwnerType
        } else {
            Write-Host "No Intune device found." -ForegroundColor Yellow
        }

        # --- Display Entra ID Details ---
        Write-Host "`n--- Entra ID Details ---" -ForegroundColor Cyan
        if ($entraDevice) {
            $entraDevice | Format-List DisplayName, OperatingSystem, OperatingSystemVersion, ApproximateLastSignInDateTime, TrustType, IsManaged, IsCompliant
        } else {
            Write-Host "No Entra ID device found." -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "An error occurred while getting device details: $_" -ForegroundColor Red
    }
}

#endregion: Commands

#region: Main Loop
function Start-Repl {
    Connect-Graph
#    if (-not $global:IsConnected) {
#        return
#    }

    while ($true) {
        $command = Read-Host "IntunePilot>"
        $parts = $command.Split(' ')
        $verb = $parts[0]
        $args = $parts[1..($parts.Length - 1)]

        switch ($verb) {
            "lsed"   { List-EntraDevices }
            "lsapd"  { List-AutopilotDevices }
            "auapd"  { 
                $p = @{}; 
                if($args.Count -ge 1) { $p.SerialNumber = $args[0] }; 
                if($args.Count -ge 2) { $p.UserPrincipalName = $args[1] }; 
                Assign-UserToAutopilotDevice @p 
            }
            "rmuapd" { 
                $p = @{}; 
                if($args.Count -ge 1) { $p.SerialNumber = $args[0] }; 
                Unassign-UserFromAutopilotDevice @p 
            }
            "lsitd"  { List-IntuneDevices }
            "rwitd"  { 
                $p = @{}; 
                if($args.Count -ge 1) { $p.DeviceName = $args[0] }; 
                Wipe-IntuneDevice @p 
            }
            "rmapd"  { 
                $p = @{}; 
                if($args.Count -ge 1) { $p.SerialNumber = $args[0] }; 
                Remove-AutopilotDevice @p 
            }
            "gdd"    { 
                $p = @{}; 
                if($args.Count -ge 1) { $p.SerialNumber = $args[0] }; 
                Get-DeviceDetails @p 
            }
            "sid"    { 
                $p = @{}; 
                if($args.Count -ge 1) { $p.DeviceName = $args[0] }; 
                Sync-IntuneDevice @p 
            }
            "ritd"   { 
                $p = @{}; 
                if($args.Count -ge 1) { $p.DeviceName = $args[0] }; 
                Retire-IntuneDevice @p 
            }
            "iapd"   { 
                $p = @{}; 
                if($args.Count -ge 1) { $p.CsvPath = $args[0] }; 
                Import-AutopilotDevice @p 
            }
            "help"   { Show-Help }
            "cls"    { Clear-Host }
            "exit"   { break }
            default { 
                if ($verb) {
                    Write-Host "Unknown command. Type 'help' for a list of commands." -ForegroundColor Yellow 
                }
            }
        }
    }
}

Start-Repl
#endregion: Main Loop
