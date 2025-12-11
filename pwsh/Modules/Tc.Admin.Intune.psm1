#requires -Modules Microsoft.Graph.DeviceManagement

Export-ModuleMember -Function `
    Get-IntuneUserDevice, Get-UserDevices, `
    Invoke-IntuneDeviceAction, Get-IntuneDeviceActionStatus `
  -Alias `
    lsdevice, lsdevices, invdevice, lsdevacts

