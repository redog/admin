function Encrypt-File {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [Parameter(Mandatory)]
        [SecureString]$Password
    )

    $FileToCheck = Get-Item -Path $Path
    $Destination = $FileToCheck.FullName + ".aes"
    
    # 1. Derive Key and IV from Password using Salt
    # We generate a random salt to prevent rainbow table attacks
    $Salt = [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(16)
    
    # RFC2898 (PBKDF2) is built-in. 100k iterations is a decent baseline.
    $DeriveBytes = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
        [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)), 
        $Salt, 
        100000, 
        [System.Security.Cryptography.HashAlgorithmName]::SHA256
    )

    $Aes = [System.Security.Cryptography.Aes]::Create()
    $Aes.Key = $DeriveBytes.GetBytes(32) # AES-256
    $Aes.IV  = $DeriveBytes.GetBytes(16)  # AES Block Size

    # 2. Setup Streams
    $FileStream = [System.IO.FileStream]::new($Destination, [System.IO.FileMode]::Create)
    
    # Write the Salt to the start of the file (we need it to decrypt)
    $FileStream.Write($Salt, 0, $Salt.Length)
    
    $CryptoStream = [System.Security.Cryptography.CryptoStream]::new(
        $FileStream, 
        $Aes.CreateEncryptor(), 
        [System.Security.Cryptography.CryptoStreamMode]::Write
    )

    $InputStream = [System.IO.FileStream]::new($FileToCheck.FullName, [System.IO.FileMode]::Open)
    
    # 3. Encrypt
    $InputStream.CopyTo($CryptoStream)
    
    # 4. Cleanup
    $InputStream.Close()
    $CryptoStream.Close()
    $FileStream.Close()
    $Aes.Dispose()
    $DeriveBytes.Dispose()

    Write-Host "Encrypted to: $Destination" -ForegroundColor Green
}
# Example
# $pass = Read-Host "Enter Password" -AsSecureString
# Encrypt-File -Path ".\secret_plans.txt" -Password $pass
