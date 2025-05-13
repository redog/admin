function Get-UserDevices {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $false, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [string]$UserPrincipalName
    )

    process {
        try {
            $selectProperties = @(
                "deviceName",
                "serialNumber",
                "manufacturer",
                "model",
                "userPrincipalName" # Included for the 'all users' scenario
            )

            if (-not [string]::IsNullOrWhiteSpace($UserPrincipalName)) {
                Write-Verbose "Attempting to retrieve devices for user: $UserPrincipalName"
                # Get the user object to ensure the UPN is valid and to get the ID
                try {
                    $user = Get-MgUser -UserId $UserPrincipalName -ErrorAction Stop -Property "Id"
                    Write-Verbose "Found user with ID: $($user.Id)"
                }
                catch {
                    Write-Error "User '$UserPrincipalName' not found or error retrieving user: $($_.Exception.Message)"
                    return
                }

                # Retrieve managed devices for the specified user
                $devices = Get-MgUserManagedDevice -UserId $user.Id -Property $selectProperties -ErrorAction Stop -All
                if ($null -eq $devices -or $devices.Count -eq 0) {
                    Write-Host "No managed devices found for $UserPrincipalName."
                    return
                }
            }
            else {
                Write-Verbose "Attempting to retrieve all managed devices."
                # Retrieve all managed devices
                $devices = Get-MgDeviceManagementManagedDevice -Property $selectProperties -ErrorAction Stop -All
                if ($null -eq $devices -or $devices.Count -eq 0) {
                    Write-Host "No managed devices found in the tenant."
                    return
                }
            }

            $output = @()
            foreach ($device in $devices) {
                $output += [PSCustomObject]@{
                    UserPrincipalName = if (-not [string]::IsNullOrWhiteSpace($UserPrincipalName)) { $UserPrincipalName } else { $device.UserPrincipalName }
                    DeviceName        = $device.DeviceName
                    SerialNumber      = $device.SerialNumber
                    Brand             = $device.Manufacturer
                    Model             = $device.Model
                }
            }

            return $output | Select-Object UserPrincipalName, DeviceName, SerialNumber, Brand, Model

        }
        catch {
            Write-Error "An error occurred: $($_.Exception.Message)"
            Write-Error "Stack Trace: $($_.ScriptStackTrace)"
        }
    }
}
