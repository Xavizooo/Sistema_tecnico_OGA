$ErrorActionPreference = 'Stop'
Write-Host ''
Write-Host 'CONFIGURACION OPENAI - ASISTENTE OGA' -ForegroundColor Cyan
Write-Host 'La clave se guardara como variable de entorno del usuario de Windows.' -ForegroundColor Gray
Write-Host 'No se guarda dentro de Sistema OGA ni en SQLite.' -ForegroundColor Gray
Write-Host ''
$secure = Read-Host 'Pegue su OPENAI_API_KEY' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    if ([string]::IsNullOrWhiteSpace($plain)) {
        throw 'No se ingreso una clave.'
    }
    [Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $plain.Trim(), 'User')
    [Environment]::SetEnvironmentVariable('OGA_AI_MODEL', 'gpt-5.6-sol', 'User')
}
finally {
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    $plain = $null
    $secure = $null
}
Write-Host ''
Write-Host 'Configuracion guardada.' -ForegroundColor Green
Write-Host 'Cierre Sistema OGA y abra una consola nueva antes de volver a ejecutar Python INICIAR.py.' -ForegroundColor Yellow
Write-Host ''
Read-Host 'Presione Enter para cerrar'
