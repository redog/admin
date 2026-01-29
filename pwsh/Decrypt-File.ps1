function Decrypt-File {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [Parameter(Mandatory)]
        [SecureString]$Password
    )

    $FileToCheck = Get-Item -Path $Path
    # Remove .aes extension if present, otherwise just append .decrypted
    if ($FileToCheck.Extension -eq ".aes") {
        $Destination = $FileToCheck.FullName -replace '\.aes$', ''
    } else {
        $Destination = $FileToCheck.FullName + ".decrypted"
    }

    # 1. Open the encrypted file stream
    $FileStream = [System.IO.FileStream]::new($FileToCheck.FullName, [System.IO.FileMode]::Open)
    
    # 2. Extract the Salt (First 16 bytes)
    $Salt = New-Object byte[](16)
    $FileStream.Read($Salt, 0, 16) | Out-Null

    # 3. Derive Key and IV (Must match the iterations/algo from encryption exactly)
    $DeriveBytes = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
        [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)), 
        $Salt, 
        100000, 
        [System.Security.Cryptography.HashAlgorithmName]::SHA256
    )

    $Aes = [System.Security.Cryptography.Aes]::Create()
    $Aes.Key = $DeriveBytes.GetBytes(32)
    $Aes.IV  = $DeriveBytes.GetBytes(16)

    # 4. Decrypt Stream
    $CryptoStream = [System.Security.Cryptography.CryptoStream]::new(
        $FileStream, 
        $Aes.CreateDecryptor(), 
        [System.Security.Cryptography.CryptoStreamMode]::Read
    )

    $OutputStream = [System.IO.FileStream]::new($Destination, [System.IO.FileMode]::Create)
    
    try {
        $CryptoStream.CopyTo($OutputStream)
        Write-Host "Decrypted to: $Destination" -ForegroundColor Green
    }
    catch {
        Write-Error "Decryption failed. Wrong password?"
    }
    finally {
        # 5. Cleanup
        $OutputStream.Close()
        $CryptoStream.Close()
        $FileStream.Close()
        $Aes.Dispose()
        $DeriveBytes.Dispose()
    }
}
# Example
# $pass = Read-Host "Enter Password" -AsSecureString
# Decrypt-File -Path ".\secret_plans.txt.aes" -Password $pass
