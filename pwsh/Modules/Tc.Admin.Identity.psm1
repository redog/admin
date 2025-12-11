#requires -Modules Microsoft.Graph.Users

function Get-UserGroupMembership {
    <#
    .SYNOPSIS
        Lists the group memberships for a user. Aliased as 'lsgrp'.

    .DESCRIPTION
        Queries Microsoft Graph to find all groups a user is a member of.
        Emits raw group membership objects; use -Verbose for progress details.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to query.

    .EXAMPLE
        PS C:\> lsgrp "user@domain.com"
    .TODO
       Not listing names and other properties properly
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [string]$UserPrincipalName
    )
    begin {
        if (-not (Test-MgGraphContext -Scopes 'User.Read.All', 'GroupMember.Read.All' -AutoConnect)) {
            return
        }
    }
    process {
        try {
            Write-Verbose "Fetching group memberships for '$UserPrincipalName'."
            $groups = Get-MgUserMemberOf -UserId $UserPrincipalName -ErrorAction Stop
            if ($null -eq $groups) {
                Write-Verbose "User '$UserPrincipalName' is not a member of any groups."
                return
            }
            $groups | Select-Object DisplayName, Id, Description | Write-Output
        }
        catch {
            Write-Error "An error occurred while fetching groups for '$($UserPrincipalName)': $($_.Exception.Message)"
        }
    }
}

function Add-UserToGroup {
    <#
    .SYNOPSIS
        Adds a user to a group. Aliased as 'addgrp'.

    .DESCRIPTION
        Adds a specified user to a specified group using their UPN and the group's display name or ID.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to add.

    .PARAMETER GroupIdentifier
        The display name or ID of the group.

    .EXAMPLE
        PS C:\> addgrp "user@domain.com" -GroupIdentifier "All Staff"
#>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$UserPrincipalName,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$GroupIdentifier
    )
    begin {
        if (-not (Test-MgGraphContext -Scopes 'User.Read.All', 'GroupMember.ReadWrite.All' -AutoConnect)) {
            return
        }
    }
    process {
        try {
            # Find the user to get their ID
            $user = Get-MgUser -UserId $UserPrincipalName -ErrorAction Stop -Property Id
            if (-not $user) {
                Write-Error "User '$($UserPrincipalName)' not found."
                return
            }

            # Find the group by ID or DisplayName
            $group = $null
            try {
                # First, try treating the identifier as a GUID (ID)
                $group = Get-MgGroup -GroupId $GroupIdentifier -ErrorAction SilentlyContinue
            } catch {}

            if (-not $group) {
                # If that fails, try searching by display name
                $foundGroups = Get-MgGroup -Filter "displayName eq '$($GroupIdentifier)'" -ErrorAction Stop
                if ($foundGroups.Count -eq 1) {
                    $group = $foundGroups
                } elseif ($foundGroups.Count -gt 1) {
                    Write-Error "Multiple groups found with the name '$($GroupIdentifier)'. Please use the group ID."
                    return
                } else {
                    Write-Error "Group '$($GroupIdentifier)' not found."
                    return
                }
            }

            if ($PSCmdlet.ShouldProcess("user '$($user.UserPrincipalName)' to group '$($group.DisplayName)'", "Add Membership")) {
                Write-Host "Adding '$($user.UserPrincipalName)' to group '$($group.DisplayName)'..." -ForegroundColor Yellow
                New-MgGroupMember -GroupId $group.Id -DirectoryObjectId $user.Id -ErrorAction Stop
                Write-Host "Successfully added user to group." -ForegroundColor Green
            }
        }
        catch {
            Write-Error "An error occurred: $($_.Exception.Message)"
        }
    }
}

function Remove-UserFromGroup {
    <#
    .SYNOPSIS
        Removes a user from a group. Aliased as 'remgrp'.

    .DESCRIPTION
        Removes a specified user from a specified group using their UPN and the group's display name or ID.

    .PARAMETER UserPrincipalName
        The User Principal Name (email address) of the user to remove.

    .PARAMETER GroupIdentifier
        The display name or ID of the group.

    .EXAMPLE
        PS C:\> remgrp "user@domain.com" -GroupIdentifier "Former Staff"
#>
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$UserPrincipalName,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$GroupIdentifier
    )
    begin {
        if (-not (Test-MgGraphContext -Scopes 'User.Read.All', 'GroupMember.ReadWrite.All' -AutoConnect)) {
            return
        }
    }
    process {
        try {
            # Find the user to get their ID
            $user = Get-MgUser -UserId $UserPrincipalName -ErrorAction Stop -Property Id
            if (-not $user) {
                Write-Error "User '$($UserPrincipalName)' not found."
                return
            }

            # Find the group by ID or DisplayName
            $group = $null
            try {
                $group = Get-MgGroup -GroupId $GroupIdentifier -ErrorAction SilentlyContinue
            } catch {}

            if (-not $group) {
                $foundGroups = Get-MgGroup -Filter "displayName eq '$($GroupIdentifier)'" -ErrorAction Stop
                if ($foundGroups.Count -eq 1) {
                    $group = $foundGroups
                } elseif ($foundGroups.Count -gt 1) {
                    Write-Error "Multiple groups found with name '$($GroupIdentifier)'. Please use the group ID."
                    return
                } else {
                    Write-Error "Group '$($GroupIdentifier)' not found."
                    return
                }
            }

            # We need the user's membership ID within the group to remove them
            $membership = Get-MgGroupMember -GroupId $group.Id -Filter "id eq '$($user.Id)'" -ErrorAction Stop
            if (-not $membership) {
                Write-Warning "User '$($user.UserPrincipalName)' is not a member of group '$($group.DisplayName)'."
                return
            }

            if ($PSCmdlet.ShouldProcess("user '$($user.UserPrincipalName)' from group '$($group.DisplayName)'", "Remove Membership")) {
                Write-Host "Removing '$($user.UserPrincipalName)' from group '$($group.DisplayName)'..." -ForegroundColor Yellow
                Remove-MgGroupMemberByRef -GroupId $group.Id -DirectoryObjectId $user.Id -ErrorAction Stop
                Write-Host "Successfully removed user from group." -ForegroundColor Green
            }
        }
        catch {
            Write-Error "An error occurred: $($_.Exception.Message)"
        }
    }
}



Export-ModuleMember -Function `
    Get-UserGroupMembership, Add-UserToGroup, Remove-UserFromGroup `
  -Alias `
    lsgrp, addgrp, remgrp
