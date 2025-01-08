# Set 2 CIDR ips or ranges to scan for printers
$printerRange = "10.3.2.0/24" 
$dhcpRange = "10.3.1.0/23"

function cidrToIpRange {
    param (
        [string] $cidrNotation
    )

    $addr, $maskLength = $cidrNotation -split '/'
    [int]$maskLen = 0
    if (-not [int32]::TryParse($maskLength, [ref] $maskLen)) {
        write-warning "No mask, setting to /32"
        $masklen = 32
    }
    if (0 -gt $maskLen -or $maskLen -gt 32) {
        throw "CIDR mask length must be between 0 and 32"
    }
    $ipAddr = [Net.IPAddress]::Parse($addr)
    if ($ipAddr -eq $null) {
        throw "Cannot parse IP address: $addr"
    }
    if ($ipAddr.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        throw "Can only process CIDR for IPv4"
    }

    $shiftCnt = 32 - $maskLen
    $mask = -bnot ((1 -shl $shiftCnt) - 1)
    $ipNum = [Net.IPAddress]::NetworkToHostOrder([BitConverter]::ToInt32($ipAddr.GetAddressBytes(), 0))
    $ipStart = ($ipNum -band $mask)
    $ipEnd = ($ipNum -bor (-bnot $mask))
    $numIPs = [Math]::Pow(2, $shiftCnt)
    $ipList = for ($i = 0; $i -lt $numIPs; $i++) {
        $currentIP = [Net.IPAddress]::HostToNetworkOrder($ipStart + $i)
        ([BitConverter]::GetBytes($currentIP) | ForEach-Object { $_ }) -join '.'
    }

    return [PSCustomObject]@{
        Start = ([BitConverter]::GetBytes([Net.IPAddress]::HostToNetworkOrder($ipStart)) | ForEach-Object { $_ }) -join '.'
        End   = ([BitConverter]::GetBytes([Net.IPAddress]::HostToNetworkOrder($ipEnd)) | ForEach-Object { $_ }) -join '.'
        List  = $ipList
    }
}

# Tests
# $ips = @('1.2.3.4/24', '9.8.7.6')
# $ips | % { cidrToIpRange $_ } | sort-object start   

# Generate IP address lists for the ranges
$printerIPs =  (cidrToIpRange $printerRange).list
$dhcpIPs = (cidrToIpRange $dhcpRange).list

function Is-IpAddressAlive {
    param(
        [string]$IP
    )
    Test-Connection -ComputerName $IP -Count 1 -Quiet
}

$jobs = @()
foreach ($ip in $printerIPs + $dhcpIPs) {
    if (Is-IpAddressAlive -IP $ip) {
		    $jobs += Start-Job -InitializationScript {
function Get-PrinterInfo {
    param(
        [string]$IP
    )
    try {
        $snmp = New-Object -ComObject "OlePrn.OleSNMP"
        $snmp.Open($IP,'public',2,1000)

        [PSCustomObject]@{
            IPAddress       = $IP
            MACAddress      = (arp -a $IP | Select-String -Pattern "([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})" | ForEach-Object { $_ -match "([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})"; $Matches[0] })
            Model           = $snmp.Get(".1.3.6.1.2.1.25.3.2.1.3.1")
            Uptime          = $snmp.Get(".1.3.6.1.2.1.1.3.0")
            MaintenanceCount = $snmp.Get(".1.3.6.1.2.1.43.10.2.1.4.1.1")
            InkName         = $snmp.Get(".1.3.6.1.2.1.43.12.1.1.4.1.1")
            InkLevel        = ([math]::Round(($snmp.Get(".1.3.6.1.2.1.43.11.1.1.9.1.1"))/($snmp.Get(".1.3.6.1.2.1.43.11.1.1.8.1.1")),2)).ToString("P0")
        }
        $snmp.Close()
    } catch {
        Write-Warning "Error getting SNMP information from ${$IP} : $($_.Exception.Message)"
    }
}
        } -ScriptBlock {
            Get-PrinterInfo -IP $args[0]
        } -ArgumentList $ip
    }
}

$results = Receive-Job -Job $jobs -Wait -AutoRemoveJob

$results | Where-Object { $_ -ne $null } | Format-Table -AutoSize

# Most of this code is stiched together from answers on the internet
