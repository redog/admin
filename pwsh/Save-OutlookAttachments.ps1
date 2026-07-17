function Save-OutlookAttachments {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)]
        [string]$FolderPath,

        [Parameter(Mandatory)]
        [string]$Sender,

        [Parameter(Mandatory)]
        [string]$Subject,

        [Parameter(Mandatory)]
        [string]$OutputPath,

        [datetime]$ReceivedAfter,

        [string]$Mailbox = 'me',

        [switch]$IncludeInlineAttachments
    )

    if (-not (Get-Command Invoke-MgGraphRequest -ErrorAction SilentlyContinue)) {
        throw 'Microsoft.Graph.Authentication is not installed. Run: Install-Module Microsoft.Graph.Authentication -Scope CurrentUser'
    }

    if (-not (Get-MgContext)) {
        Connect-MgGraph -Scopes Mail.Read -NoWelcome
    }

    New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
    $OutputPath = (Resolve-Path -LiteralPath $OutputPath).Path

    $baseUri = if ($Mailbox -eq 'me') {
        'https://graph.microsoft.com/v1.0/me'
    }
    else {
        $encodedMailbox = [uri]::EscapeDataString($Mailbox)
        "https://graph.microsoft.com/v1.0/users/$encodedMailbox"
    }

    function Get-AllGraphPages {
        param(
            [Parameter(Mandatory)]
            [string]$Uri
        )

        do {
            $page = Invoke-MgGraphRequest `
                -Method GET `
                -Uri $Uri `
                -OutputType PSObject

            foreach ($item in @($page.value)) {
                $item
            }

            $Uri = $page.'@odata.nextLink'
        }
        while ($Uri)
    }

    function Resolve-MailFolderPath {
        param(
            [Parameter(Mandatory)]
            [string]$Path
        )

        $parts = @(
            $Path -split '[\\/]' |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )

        if ($parts.Count -eq 0) {
            throw "Invalid folder path: $Path"
        }

        $currentFolderId = $null

        foreach ($part in $parts) {
            if ($null -eq $currentFolderId) {
                $uri = "$baseUri/mailFolders?`$top=100&`$select=id,displayName"
            }
            else {
                $encodedFolderId = [uri]::EscapeDataString($currentFolderId)
                $uri = "$baseUri/mailFolders/$encodedFolderId/childFolders?`$top=100&`$select=id,displayName"
            }

            $matches = @(
                Get-AllGraphPages -Uri $uri |
                    Where-Object { $_.displayName -ieq $part }
            )

            if ($matches.Count -eq 0) {
                throw "Could not find '$part' while resolving folder path '$Path'."
            }

            if ($matches.Count -gt 1) {
                throw "More than one folder named '$part' was found under the same parent."
            }

            $currentFolderId = $matches[0].id
        }

        $currentFolderId
    }

    function ConvertTo-SafeFileName {
        param(
            [Parameter(Mandatory)]
            [string]$Name
        )

        foreach ($character in [IO.Path]::GetInvalidFileNameChars()) {
            $Name = $Name.Replace([string]$character, '_')
        }

        $Name = $Name.Trim().TrimEnd('.')

        if ([string]::IsNullOrWhiteSpace($Name)) {
            $Name = 'attachment.bin'
        }

        $Name
    }

    function Get-AvailableFilePath {
        param(
            [Parameter(Mandatory)]
            [string]$Directory,

            [Parameter(Mandatory)]
            [string]$FileName
        )

        $candidate = Join-Path $Directory $FileName

        if (-not (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }

        $stem = [IO.Path]::GetFileNameWithoutExtension($FileName)
        $extension = [IO.Path]::GetExtension($FileName)
        $counter = 1

        do {
            $candidate = Join-Path $Directory (
                '{0}_{1}{2}' -f $stem, $counter, $extension
            )
            $counter++
        }
        while (Test-Path -LiteralPath $candidate)

        $candidate
    }

    $folderId = Resolve-MailFolderPath -Path $FolderPath
    $encodedFolderId = [uri]::EscapeDataString($folderId)

    $escapedSender = $Sender.Replace("'", "''")
    $escapedSubject = $Subject.Replace("'", "''")

    $filters = [System.Collections.Generic.List[string]]::new()
    $filters.Add("from/emailAddress/address eq '$escapedSender'")
    $filters.Add("subject eq '$escapedSubject'")
    $filters.Add('hasAttachments eq true')

    if ($PSBoundParameters.ContainsKey('ReceivedAfter')) {
        $dateString = $ReceivedAfter.ToUniversalTime().ToString(
            'yyyy-MM-ddTHH:mm:ssZ',
            [Globalization.CultureInfo]::InvariantCulture
        )

        $filters.Add("receivedDateTime ge $dateString")
    }

    $filter = [uri]::EscapeDataString(($filters -join ' and '))

    $messageUri = (
        "$baseUri/mailFolders/$encodedFolderId/messages" +
        "?`$top=100" +
        "&`$select=id,subject,receivedDateTime,from,hasAttachments" +
        "&`$filter=$filter"
    )

    $messageCount = 0
    $attachmentCount = 0

    foreach ($message in Get-AllGraphPages -Uri $messageUri) {
        $messageCount++

        $encodedMessageId = [uri]::EscapeDataString($message.id)

        $attachmentUri = (
            "$baseUri/messages/$encodedMessageId/attachments" +
            "?`$top=100" +
            "&`$select=id,name,contentType,size,isInline"
        )

        foreach ($attachment in Get-AllGraphPages -Uri $attachmentUri) {
            if ($attachment.'@odata.type' -ne '#microsoft.graph.fileAttachment') {
                Write-Verbose "Skipping non-file attachment '$($attachment.name)'."
                continue
            }

            if (
                $attachment.isInline -and
                -not $IncludeInlineAttachments
            ) {
                continue
            }

            $received = [datetimeoffset]$message.receivedDateTime
            $timestamp = $received.UtcDateTime.ToString('yyyyMMdd_HHmmss')

            $safeName = ConvertTo-SafeFileName -Name $attachment.name
            $fileName = "${timestamp}_$safeName"
            $destination = Get-AvailableFilePath `
                -Directory $OutputPath `
                -FileName $fileName

            $encodedAttachmentId = [uri]::EscapeDataString($attachment.id)
            $downloadUri = (
                "$baseUri/messages/$encodedMessageId/" +
                "attachments/$encodedAttachmentId/`$value"
            )

            if ($PSCmdlet.ShouldProcess(
                $destination,
                "Download '$($attachment.name)'"
            )) {
                Invoke-MgGraphRequest `
                    -Method GET `
                    -Uri $downloadUri `
                    -OutputFilePath $destination

                $attachmentCount++

                [pscustomobject]@{
                    Received       = $received
                    Sender         = $message.from.emailAddress.address
                    Subject        = $message.subject
                    AttachmentName = $attachment.name
                    SizeBytes      = [long]$attachment.size
                    SavedAs        = $destination
                }
            }
        }
    }

    Write-Verbose "Matched $messageCount messages and downloaded $attachmentCount attachments."
}
