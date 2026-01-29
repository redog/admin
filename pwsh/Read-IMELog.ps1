function Read-IMELog {
    <#
    .SYNOPSIS
      Human-friendly reader for Intune Management Extension CMTrace logs.

    .DESCRIPTION
      Parses lines like:
        <![LOG[Message text]LOG]!><time="10:11:12.345-300" date="10-21-2025" component="Win32App" type="1" thread="0x1234" file="..." line="...">
      Outputs clean text or objects. Supports -Follow, -Tail, -Since, -Component, -MinLevel filtering.

    .PARAMETER Path
      Path to a single log file (e.g., C:\ProgramData\Microsoft\IntuneManagementExtension\Logs\IntuneManagementExtension.log)

    .PARAMETER Follow
      Stream the log (like tail -f).

    .PARAMETER Tail
      Show only the last N lines.

    .PARAMETER Since
      Only show entries at or after this time (DateTime). Accepts strings convertible to [datetime].

    .PARAMETER Component
      Filter by component name (exact or regex with -ComponentRegex).

    .PARAMETER ComponentRegex
      Treat -Component as regex.

    .PARAMETER MinLevel
      Minimum level to include: Info=1, Warn=2, Error=3.

    .PARAMETER AsObject
      Output PSCustomObject instead of colorized text.

    .PARAMETER NoColor
      Disable color.

    .EXAMPLE
      Read-IMELog -Path 'C:\ProgramData\Microsoft\IntuneManagementExtension\Logs\IntuneManagementExtension.log' -Tail 200

    .EXAMPLE
      Read-IMELog -Path .\IntuneManagementExtension.log -Follow -MinLevel 2   # only warnings/errors

    .EXAMPLE
      Read-IMELog -Path .\AgentExecutor.log -Since (Get-Date).AddHours(-1) -Component 'Win32App' -AsObject
    #>

    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [switch]$Follow,
        [int]$Tail = 0,
        [datetime]$Since,
        [string]$Component,
        [switch]$ComponentRegex,
        [ValidateSet(1,2,3)][int]$MinLevel = 1,
        [switch]$AsObject,
        [switch]$NoColor
    )

    begin {
        $ErrorActionPreference = 'Stop'

        function _LevelName([int]$t) {
            switch ($t) { 3 {'Error'} 2 {'Warn'} default {'Info'} }
        }
        function _LevelColor([int]$t) {
            switch ($t) { 3 {'Red'} 2 {'Yellow'} default {'Gray'} }
        }

        # Date parsing helper (safe for Windows PowerShell + pwsh)
        function _Parse-LocalDate([string]$dateStr, [string]$timeStr) {
            if ([string]::IsNullOrWhiteSpace($dateStr) -or [string]::IsNullOrWhiteSpace($timeStr)) { return $null }
            $timeNoOffset = $timeStr -replace '([+-]\d+)$',''
            $combo = "$dateStr $timeNoOffset"
            $ci   = [System.Globalization.CultureInfo]::InvariantCulture
            $fmtS = @('MM-dd-yyyy HH:mm:ss.fff','MM-dd-yyyy HH:mm:ss','M-d-yyyy HH:mm:ss.fff','M-d-yyyy HH:mm:ss')
            foreach ($f in $fmtS) {
                try {
                    $tmp = [datetime]::ParseExact($combo, $f, $ci, [System.Globalization.DateTimeStyles]::AssumeLocal)
                    return [datetime]::SpecifyKind($tmp, [System.DateTimeKind]::Local)
                } catch { }
            }
            return $null
        }

        $hasCMTracePattern = [regex]'<!\[LOG\[(.*?)\]LOG\]!>(.*)$'
        $kvPattern         = [regex]'(\w+)="([^"]*)"'

        if (-not (Test-Path -LiteralPath $Path)) {
            throw "Path not found: $Path"
        }

        $getContentParams = @{ LiteralPath = $Path; Encoding = 'UTF8'; ErrorAction = 'Stop' }
        if ($Tail -gt 0) { $getContentParams['Tail'] = $Tail }
        if ($Follow)     { $getContentParams['Wait'] = $true }

        function _Parse-Line([string]$line) {
            if ([string]::IsNullOrWhiteSpace($line)) { return $null }

            $m = $hasCMTracePattern.Match($line)
            if ($m.Success) {
                $msg = $m.Groups[1].Value
                $attrText = $m.Groups[2].Value
                $attrs = [ordered]@{}
                foreach ($kv in $kvPattern.Matches($attrText)) {
                    $attrs[$kv.Groups[1].Value] = $kv.Groups[2].Value
                }
                $dateStr = $attrs['date']
                $timeStr = $attrs['time']
                $dtLocal = _Parse-LocalDate $dateStr $timeStr
                $lvl = ($attrs['type'] -as [int]); if (-not $lvl) { $lvl = 1 }
                [pscustomobject]@{
                    TimeUTC    = ($dtLocal ? $dtLocal.ToUniversalTime() : $null)
                    TimeLocal  = $dtLocal
                    Date       = $dateStr
                    Component  = $attrs['component']
                    Level      = $lvl
                    LevelName  = _LevelName $lvl
                    Thread     = $attrs['thread']
                    File       = $attrs['file']
                    Line       = $attrs['line']
                    Message    = $msg
                    Raw        = $line
                }
            }
            else {
                [pscustomobject]@{
                    TimeUTC    = $null
                    TimeLocal  = $null
                    Date       = $null
                    Component  = $null
                    Level      = 1
                    LevelName  = 'Info'
                    Thread     = $null
                    File       = $null
                    Line       = $null
                    Message    = $line.Trim()
                    Raw        = $line
                }
            }
        }

        function _Include([pscustomobject]$o) {
            if (-not $o) { return $false }
            if ($o.Level -lt $MinLevel) { return $false }
            if ($Since -and $o.TimeLocal -and ($o.TimeLocal -lt $Since)) { return $false }
            if ($Component) {
                if ($ComponentRegex) { if (-not ($o.Component -match $Component)) { return $false } }
                else { if ($o.Component -ne $Component) { return $false } }
            }
            return $true
        }

        function _Print([pscustomobject]$o) {
            if ($AsObject) { return $o }
            $ts = if ($o.TimeLocal) { $o.TimeLocal.ToString('yyyy-MM-dd HH:mm:ss.fff') } else { '......................' }
            $comp = if ($o.Component) { $o.Component } else { '-' }
            $lineInfo = if ($o.File -and $o.Line) { " ($($o.File):$($o.Line))" } else { '' }
            $thread  = if ($o.Thread) { " [$($o.Thread)]" } else { '' }
            $text = "[$ts] [$comp] [$($o.LevelName)]$thread$lineInfo  $($o.Message)"
            if ($NoColor) { Write-Host $text }
            else { Write-Host $text -ForegroundColor (_LevelColor $o.Level) }
        }
    }

    process {
        $stream = Get-Content @getContentParams
        foreach ($line in $stream) {
            $obj = _Parse-Line $line
            if (_Include $obj) {
                $out = _Print $obj
                if ($AsObject -and $out) { $out }
            }
        }
    }
}
