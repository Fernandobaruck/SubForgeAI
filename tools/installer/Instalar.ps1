param([string]$DestinationParent, [string]$SourceDirectory, [switch]$NoLaunch, [ValidateRange(1,8)][int]$Connections = 4,
      [string]$DestinationPath, [string]$ProgressPath, [string]$ControlPath, [int]$ParentProcessId = 0)
$ErrorActionPreference = 'Stop'
if ($ProgressPath) { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false) }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::DefaultConnectionLimit = 8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.IO.Compression.FileSystem
$version = '__VERSION__'
$repository = '__REPOSITORY__'
$release = "https://github.com/$repository/releases/download/v$version/"
$cache = Join-Path $env:LOCALAPPDATA "SubForgeAI-install\$version"
New-Item -ItemType Directory -Path $cache -Force | Out-Null
$script:stateClock = [Diagnostics.Stopwatch]::StartNew()
$script:lastStateAt = -1000L
$script:lastStage = ''
$script:verifyDone = 0L
$script:verifyTotal = 0L
$cacheLock = $null
$stage = $null
$committed = $false

function Publish-State([string]$phase, [long]$done=0, [long]$total=0, [double]$speed=0, [string]$message='') {
    if (-not $ProgressPath) { return }
    if ($phase -eq $script:lastStage -and $done -ne $total -and $script:stateClock.ElapsedMilliseconds-$script:lastStateAt -lt 250) { return }
    $record = @{ stage=$phase; completed=$done; total=$total; speed=$speed; message=$message; destination=$destination; version=$version }
    $temporary = $ProgressPath + '.new'
    [IO.File]::WriteAllText($temporary,($record | ConvertTo-Json -Compress),[Text.Encoding]::UTF8)
    try {
        if ([IO.File]::Exists($ProgressPath)) { [IO.File]::Replace($temporary,$ProgressPath,[NullString]::Value) }
        else { [IO.File]::Move($temporary,$ProgressPath) }
    } catch [UnauthorizedAccessException] {
        # Some restricted Windows profiles allow writes but deny rename. The
        # GUI tolerates a partial JSON read and retries on its next timer tick.
        [IO.File]::WriteAllText($ProgressPath,($record | ConvertTo-Json -Compress),[Text.Encoding]::UTF8)
    }
    $script:lastStage=$phase; $script:lastStateAt=$script:stateClock.ElapsedMilliseconds
}
function Control-Action {
    if (-not $ControlPath -or -not [IO.File]::Exists($ControlPath)) { return '' }
    try {
        if ((Get-Item -LiteralPath $ControlPath).Length -gt 4096) { return '' }
        $action = ([IO.File]::ReadAllText($ControlPath) | ConvertFrom-Json).action
        if ($action -in @('pause','resume','cancel')) { return $action }
    } catch { }
    return ''
}
function Assert-Running {
    if ((Control-Action) -eq 'cancel') { throw [OperationCanceledException]::new('Instalação cancelada. Os downloads parciais foram preservados.') }
    if ($ParentProcessId -gt 0) {
        try { $parentProcess=[Diagnostics.Process]::GetProcessById($ParentProcessId); $alive=-not $parentProcess.HasExited; $parentProcess.Dispose() } catch { $alive=$false }
        if (-not $alive) { throw [OperationCanceledException]::new('O instalador foi fechado. Downloads parciais preservados.') }
    }
}

function File-Sha256([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        $buffer=New-Object byte[] (4MB)
        while (($count=$stream.Read($buffer,0,$buffer.Length)) -gt 0) {
            Assert-Running
            $null=$hash.TransformBlock($buffer,0,$count,$buffer,0)
            $script:verifyDone+=$count
            Publish-State 'verify' $script:verifyDone $script:verifyTotal
        }
        $null=$hash.TransformFinalBlock((New-Object byte[] 0),0,0)
        return [BitConverter]::ToString($hash.Hash).Replace('-', '').ToLowerInvariant()
    }
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
        $clock = [Diagnostics.Stopwatch]::StartNew()
        $lastProgress = -250L
        while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            Assert-Running
            if ($expected -gt 0 -and $done + $count -gt $expected) { throw 'Download maior que o tamanho esperado.' }
            if ($expected -eq 0 -and $done + $count -gt 1048576) { throw 'Manifesto maior que o limite permitido.' }
            $output.Write($buffer, 0, $count); $done += $count
            # Rendering console progress on every network read can throttle fast downloads.
            if ($expected -gt 0 -and $clock.ElapsedMilliseconds - $lastProgress -ge 250) {
                $speed = ($done - $offset) / 1MB / [Math]::Max(0.001, $clock.Elapsed.TotalSeconds)
                Write-Progress -Activity 'Baixando aplicativo' -Status ('{0} - {1:N1} MB/s' -f ([IO.Path]::GetFileName($path)), $speed) -PercentComplete ([Math]::Min(100, 100*$done/$expected))
                $lastProgress = $clock.ElapsedMilliseconds
            }
        }
        if ($expected -gt 0) { Write-Progress -Activity 'Baixando aplicativo' -Completed }
        if ($expected -gt 0 -and $done -ne $expected) { throw 'Download incompleto. Abra Instalar.cmd novamente para retomar.' }
    } finally { $inputStream.Dispose(); $output.Dispose(); $response.Dispose() }
}

try {
    Write-Host "SubForgeAI Studio $version - instalação inicial" -ForegroundColor Magenta
    Write-Host 'Escolha a pasta onde será criada a pasta do aplicativo. Não é necessário executar como administrador.'
    if (-not $DestinationParent -and -not $DestinationPath) {
        $picker = New-Object Windows.Forms.FolderBrowserDialog
        $picker.Description = 'Escolha onde instalar o SubForgeAI Studio'
        $picker.SelectedPath = [Environment]::GetFolderPath('MyDocuments')
        if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { exit 0 }
        $DestinationParent = $picker.SelectedPath
    }
    if ($DestinationPath) {
        if (-not [IO.Path]::IsPathRooted($DestinationPath)) { throw 'Escolha um caminho absoluto para instalar.' }
        $destination=[IO.Path]::GetFullPath($DestinationPath).TrimEnd('\')
        $DestinationParent=[IO.Path]::GetDirectoryName($destination)
    } else { $destination = [IO.Path]::GetFullPath((Join-Path $DestinationParent "SubForgeAI-$version")) }
    if (Test-Path -LiteralPath $destination) { throw "A pasta já existe: $destination. Escolha outra pasta para preservar seus arquivos." }
    if (-not (Test-Path -LiteralPath $DestinationParent -PathType Container)) { throw 'A pasta que receberá o aplicativo não existe. Use Escolher pasta.' }
    try { $cacheLock=[IO.File]::Open((Join-Path $cache '.install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
    catch { throw 'Outro instalador desta versão está em execução. Feche-o antes de continuar.' }
    Assert-Running
    Publish-State 'prepare'
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
    if ($manifest.parts.Count -lt 1 -or $manifest.parts.Count -gt 50 -or $manifest.raw_size -lt 1 -or $manifest.raw_size -gt 100GB -or $manifest.zip_size -lt 1 -or $manifest.zip_size -gt 50GB -or $manifest.zip_sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Manifesto inválido.' }
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
    }
    if (($manifest.parts | Measure-Object size -Sum).Sum -ne $manifest.zip_size) { throw 'Tamanhos das partes inconsistentes.' }
    $enginePath = Join-Path $PSScriptRoot 'DownloadEngine.cs'
    if (-not $SourceDirectory -and (Test-Path -LiteralPath $enginePath)) {
        if (-not ('SubForgeDownloadSession' -as [type])) { Add-Type -Path $enginePath }
        $urls = [string[]]@($manifest.parts | ForEach-Object { $release + $_.name })
        $paths = [string[]]@($manifest.parts | ForEach-Object { Join-Path $cache $_.name })
        $sizes = [long[]]@($manifest.parts | ForEach-Object { [long]$_.size })
        $finished=$false; $pausedDone=0L; $pausedTotal=[long]$manifest.zip_size
        while (-not $finished) {
            Assert-Running
            while ((Control-Action) -eq 'pause') { Publish-State 'paused' $pausedDone $pausedTotal; Assert-Running; Start-Sleep -Milliseconds 200 }
            $download = [SubForgeDownloadSession]::Start($urls, $paths, $sizes, $Connections)
            $clock = [Diagnostics.Stopwatch]::StartNew()
            $paused=$false
            try {
            Write-Host ("Download nativo: até {0} partes simultâneas. Arquivos parciais serão aproveitados." -f $Connections)
            while (-not $download.IsCompleted) {
                Assert-Running
                if ((Control-Action) -eq 'pause') {
                    $download.Cancel()
                    try { $download.Wait() } catch { }
                    $paused=$true
                    $pausedDone=$download.Completed; $pausedTotal=$download.Total
                    Publish-State 'paused' $download.Completed $download.Total
                    break
                }
                $speed = [Math]::Max(0, $download.Completed - $download.Initial) / 1MB / [Math]::Max(0.001, $clock.Elapsed.TotalSeconds)
                Publish-State 'download' $download.Completed $download.Total ($speed*1MB)
                $remaining = '--'
                if ($speed -gt 0) { $remaining = '{0:N0} min' -f (($download.Total - $download.Completed) / 1MB / $speed / 60) }
                Write-Progress -Activity 'Baixando aplicativo' -Status ('{0:N1} MB/s - restante estimado: {1}' -f $speed, $remaining) -PercentComplete ([Math]::Min(100, 100*$download.Completed/$download.Total))
                Start-Sleep -Milliseconds 250
            }
            if (-not $paused) { $download.Wait(); $finished=$true }
            } finally {
                $download.Cancel()
                try { $download.Wait() } catch { }
                $download.Dispose()
            Write-Progress -Activity 'Baixando aplicativo' -Completed
            }
        }
    }
    $script:verifyDone=0L; $script:verifyTotal=[long]$manifest.zip_size
    Publish-State 'verify' 0 $script:verifyTotal
    foreach ($part in $manifest.parts) {
        $path = Join-Path $cache $part.name
        Download-File ($release + $part.name) $path $part.size
        Write-Host ('Verificando ' + $part.name)
        if ((File-Sha256 $path) -ne $part.sha256) { Remove-Item -LiteralPath $path; throw 'Falha na verificação. Execute o instalador novamente para baixar a parte afetada.' }
    }
    Write-Host 'Preparando arquivos. Aguarde...'
    Assert-Running
    Publish-State 'combine' 0 ([long]$manifest.zip_size)
    $zipPath = Join-Path $cache 'portable.zip'
    $combined = [IO.File]::Create($zipPath)
    try {
        foreach ($part in $manifest.parts) {
            $inputStream = [IO.File]::OpenRead((Join-Path $cache $part.name))
            try {
                $buffer=New-Object byte[] (4MB)
                while (($count=$inputStream.Read($buffer,0,$buffer.Length)) -gt 0) {
                    Assert-Running; $combined.Write($buffer,0,$count)
                    Publish-State 'combine' $combined.Position ([long]$manifest.zip_size)
                }
            } finally { $inputStream.Dispose() }
        }
    } finally { $combined.Dispose() }
    $script:verifyDone=0L; $script:verifyTotal=[long]$manifest.zip_size
    if ((Get-Item -LiteralPath $zipPath).Length -ne $manifest.zip_size -or (File-Sha256 $zipPath) -ne $manifest.zip_sha256) { throw 'Falha na integridade do pacote completo.' }
    $stage = $destination + '.installing-' + [Guid]::NewGuid().ToString('N')
    $zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        foreach ($entry in $zip.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $stage $entry.FullName))
            if (-not $target.StartsWith($stage + '\', [StringComparison]::OrdinalIgnoreCase) -or $entry.FullName.Contains(':')) { throw 'Caminho inválido no pacote.' }
        }
        $rawTotal=($zip.Entries | Measure-Object Length -Sum).Sum
        if ($rawTotal -gt [long]$manifest.raw_size+1MB) { throw 'Tamanho extraído maior que o manifesto.' }
        [IO.Directory]::CreateDirectory($stage) | Out-Null
        $extracted=0L
        $buffer=New-Object byte[] (1MB)
        Publish-State 'extract' 0 $rawTotal
        foreach ($entry in $zip.Entries) {
            Assert-Running
            $target=[IO.Path]::GetFullPath((Join-Path $stage $entry.FullName))
            if ($entry.FullName.EndsWith('/') -or $entry.FullName.EndsWith('\')) { [IO.Directory]::CreateDirectory($target) | Out-Null; continue }
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            $inputStream=$entry.Open(); $outputStream=[IO.File]::Open($target,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
            try {
                while (($count=$inputStream.Read($buffer,0,$buffer.Length)) -gt 0) {
                    Assert-Running; $outputStream.Write($buffer,0,$count); $extracted+=$count
                    Publish-State 'extract' $extracted $rawTotal
                }
            } finally { $inputStream.Dispose(); $outputStream.Dispose() }
        }
    } finally { $zip.Dispose() }
    if (-not (Test-Path -LiteralPath (Join-Path $stage 'SubForgeAI Studio.exe'))) { throw 'Aplicativo ausente no pacote.' }
    Assert-Running
    Move-Item -LiteralPath $stage -Destination $destination
    $committed=$true
    foreach ($part in $manifest.parts) { Remove-Item -LiteralPath (Join-Path $cache $part.name) }
    Remove-Item -LiteralPath $zipPath
    Write-Host "Instalação concluída: $destination" -ForegroundColor Green
    Write-Host 'No Studio, clique em Preparar para começar para baixar os modelos desejados.'
    Publish-State 'complete' 1 1
    if (-not $NoLaunch) { Start-Process -FilePath (Join-Path $destination 'SubForgeAI Studio.exe') -WorkingDirectory $destination }
} catch {
    $cancelled=$_.Exception -is [OperationCanceledException]
    $failure=$_.Exception.Message
    if ($stage -and -not $committed -and (Test-Path -LiteralPath $stage)) {
        $resolved=[IO.Path]::GetFullPath($stage)
        if ($resolved.StartsWith($destination+'.installing-',[StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetDirectoryName($resolved) -eq [IO.Path]::GetDirectoryName($destination)) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
    if ($cancelled) { Publish-State 'cancelled' 0 0 0 $failure } else { Publish-State 'error' 0 0 0 $failure }
    Write-Host ('Não foi possível concluir: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Os downloads parciais válidos foram preservados. Execute Instalar.cmd novamente para retomar.'
    if ($cancelled) { exit 2 } else { exit 1 }
} finally { if ($cacheLock) { $cacheLock.Dispose() } }
