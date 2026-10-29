param([string]$DestinationParent, [string]$SourceDirectory, [switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.IO.Compression.FileSystem
$version = '__VERSION__'
$repository = '__REPOSITORY__'
$release = "https://github.com/$repository/releases/download/v$version/"
$cache = Join-Path $env:LOCALAPPDATA "SubForgeAI-install\$version"
New-Item -ItemType Directory -Path $cache -Force | Out-Null

function File-Sha256([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $hash.Dispose() }
}

function Download-File([string]$url, [string]$path, [long]$expected) {
    if ($SourceDirectory) {
        Copy-Item -LiteralPath (Join-Path $SourceDirectory ([IO.Path]::GetFileName(([Uri]$url).AbsolutePath))) -Destination $path -Force
        return
    }
    $offset = 0L
    if (Test-Path -LiteralPath $path) { $offset = (Get-Item -LiteralPath $path).Length }
    if ($expected -gt 0 -and $offset -eq $expected) { return }
    if ($expected -gt 0 -and $offset -gt $expected) { throw 'Arquivo parcial inválido. Remova somente o arquivo indicado: ' + $path }
    $request = [Net.HttpWebRequest]::Create($url)
    $request.UserAgent = 'SubForgeAI-installer'
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 30000
    if ($offset -gt 0) { $request.AddRange($offset) }
    $response = $request.GetResponse()
    if ($offset -gt 0 -and [int]$response.StatusCode -ne 206) { $offset = 0L }
    $mode = [IO.FileMode]::Create
    if ($offset -gt 0) { $mode = [IO.FileMode]::Append }
    $output = [IO.File]::Open($path, $mode, [IO.FileAccess]::Write)
    $inputStream = $response.GetResponseStream()
    try {
        $buffer = New-Object byte[] (1024*1024)
        $done = $offset
        while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($expected -gt 0 -and $done + $count -gt $expected) { throw 'Download maior que o tamanho esperado.' }
            if ($expected -eq 0 -and $done + $count -gt 1048576) { throw 'Manifesto maior que o limite permitido.' }
            $output.Write($buffer, 0, $count); $done += $count
            if ($expected -gt 0) { Write-Progress -Activity 'Baixando aplicativo' -Status ([IO.Path]::GetFileName($path)) -PercentComplete ([Math]::Min(100, 100*$done/$expected)) }
        }
        if ($expected -gt 0 -and $done -ne $expected) { throw 'Download incompleto. Abra Instalar.cmd novamente para retomar.' }
    } finally { $inputStream.Dispose(); $output.Dispose(); $response.Dispose() }
}

try {
    Write-Host "SubForgeAI Studio $version - instalação inicial" -ForegroundColor Magenta
    Write-Host 'Escolha a pasta onde será criada a pasta do aplicativo. Não é necessário executar como administrador.'
    if (-not $DestinationParent) {
        $picker = New-Object Windows.Forms.FolderBrowserDialog
        $picker.Description = 'Escolha onde instalar o SubForgeAI Studio'
        $picker.SelectedPath = [Environment]::GetFolderPath('MyDocuments')
        if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { exit 0 }
        $DestinationParent = $picker.SelectedPath
    }
    $destination = [IO.Path]::GetFullPath((Join-Path $DestinationParent "SubForgeAI-$version"))
    if (Test-Path -LiteralPath $destination) { throw "A pasta já existe: $destination. Escolha outra pasta para preservar seus arquivos." }
    $probe = Join-Path $DestinationParent ('.subforge-write-' + [Guid]::NewGuid().ToString('N'))
    [IO.File]::WriteAllText($probe, 'write check')
    [IO.File]::Delete($probe)
    $manifestPath = Join-Path $cache 'manifest.json'
    # Small manifest is fetched afresh, rather than resuming an old response.
    if (Test-Path -LiteralPath $manifestPath) { Remove-Item -LiteralPath $manifestPath }
    Download-File ($release + "SubForgeAI-portable-$version.manifest.json") $manifestPath 0
    $envelope = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $payloadBytes = [Convert]::FromBase64String($envelope.payload_b64)
    $signature = [Convert]::FromBase64String($envelope.signature)
    $blob = [Convert]::FromBase64String('__PUBLIC_KEY__')
    $exponentLength = [BitConverter]::ToInt32($blob, 8)
    $modulusLength = [BitConverter]::ToInt32($blob, 12)
    $parameters = New-Object Security.Cryptography.RSAParameters
    $parameters.Exponent = $blob[24..(23+$exponentLength)]
    $parameters.Modulus = $blob[(24+$exponentLength)..(23+$exponentLength+$modulusLength)]
    $rsa = New-Object Security.Cryptography.RSACryptoServiceProvider
    try {
        $rsa.ImportParameters($parameters)
        if (-not $rsa.VerifyData($payloadBytes, [Security.Cryptography.CryptoConfig]::MapNameToOID('SHA256'), $signature)) { throw 'Assinatura do pacote inválida.' }
    } finally { $rsa.Dispose() }
    $manifest = [Text.Encoding]::UTF8.GetString($payloadBytes) | ConvertFrom-Json
    if ($manifest.schema -ne 'subforge-portable-1' -or $manifest.repository -ne $repository -or $manifest.version -ne $version) { throw 'Pacote incompatível.' }
    if ($manifest.parts.Count -lt 1 -or $manifest.parts.Count -gt 50 -or $manifest.raw_size -gt 100GB -or $manifest.zip_size -gt 50GB) { throw 'Manifesto inválido.' }
    Write-Host ('Download do aplicativo: {0:N2} GB. Instalado: {1:N2} GB, sem modelos.' -f ($manifest.zip_size/1GB), ($manifest.raw_size/1GB))
    $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($destination))
    if ($drive.AvailableFreeSpace -lt [long]$manifest.raw_size + 2GB) { throw 'Espaço insuficiente na pasta de destino.' }
    $cacheDrive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($cache))
    $requiredCache = 2*[long]$manifest.zip_size + 1GB
    if ($drive.Name -eq $cacheDrive.Name) { $requiredCache += [long]$manifest.raw_size }
    if ($cacheDrive.AvailableFreeSpace -lt $requiredCache) { throw 'Espaço insuficiente para preparar o download. Libere espaço no disco do perfil do Windows.' }
    $seen = @{}
    foreach ($part in $manifest.parts) {
        if ($part.name -notmatch '^SubForgeAI-portable-\d+\.\d+\.\d+\.part\d{2}\.bin$' -or $seen.ContainsKey($part.name) -or $part.size -lt 1 -or $part.size -gt 1GB -or $part.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Parte de instalação inválida.' }
        $seen[$part.name] = $true
        $path = Join-Path $cache $part.name
        Download-File ($release + $part.name) $path $part.size
        Write-Host ('Verificando ' + $part.name)
        if ((File-Sha256 $path) -ne $part.sha256) { Remove-Item -LiteralPath $path; throw 'Falha na verificação. Execute o instalador novamente para baixar a parte afetada.' }
    }
    Write-Host 'Preparando arquivos. Aguarde...'
    $zipPath = Join-Path $cache 'portable.zip'
    $combined = [IO.File]::Create($zipPath)
    try {
        foreach ($part in $manifest.parts) {
            $inputStream = [IO.File]::OpenRead((Join-Path $cache $part.name))
            try { $inputStream.CopyTo($combined) } finally { $inputStream.Dispose() }
        }
    } finally { $combined.Dispose() }
    if ((Get-Item -LiteralPath $zipPath).Length -ne $manifest.zip_size -or (File-Sha256 $zipPath) -ne $manifest.zip_sha256) { throw 'Falha na integridade do pacote completo.' }
    $stage = $destination + '.installing-' + [Guid]::NewGuid().ToString('N')
    $zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        foreach ($entry in $zip.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $stage $entry.FullName))
            if (-not $target.StartsWith($stage + '\', [StringComparison]::OrdinalIgnoreCase) -or $entry.FullName.Contains(':')) { throw 'Caminho inválido no pacote.' }
        }
    } finally { $zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $stage)
    if (-not (Test-Path -LiteralPath (Join-Path $stage 'SubForgeAI Studio.exe'))) { throw 'Aplicativo ausente no pacote.' }
    Move-Item -LiteralPath $stage -Destination $destination
    foreach ($part in $manifest.parts) { Remove-Item -LiteralPath (Join-Path $cache $part.name) }
    Remove-Item -LiteralPath $zipPath
    Write-Host "Instalação concluída: $destination" -ForegroundColor Green
    Write-Host 'No Studio, clique em Preparar para começar para baixar os modelos desejados.'
    if (-not $NoLaunch) { Start-Process -FilePath (Join-Path $destination 'SubForgeAI Studio.exe') -WorkingDirectory $destination }
} catch {
    Write-Host ('Não foi possível concluir: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Os downloads parciais válidos foram preservados. Execute Instalar.cmd novamente para retomar.'
    exit 1
}
