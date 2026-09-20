param([ValidateSet('start', 'stop', 'status')][string]$Action = 'status')

$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot 'backend/.runtime/launcher'

function Get-OwnedProcess($Record) {
    $process = Get-Process -Id $Record.pid -ErrorAction SilentlyContinue
    # 同时核对创建时间，避免 PID 被复用后停止无关进程。
    if ($process -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $Record.started) {
        return $process
    }
    return $null
}

function Get-ServiceRecords {
    foreach ($file in Get-ChildItem -LiteralPath $RuntimeDir -Filter '*.json') {
        Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    }
}

function Start-HausService([string]$Name, [string]$Directory, [string]$Command) {
    $wrapper = Join-Path $RuntimeDir "$Name.cmd"
    $stdout = Join-Path $RuntimeDir "$Name.stdout.log"
    $stderr = Join-Path $RuntimeDir "$Name.stderr.log"
    $lines = @('@echo off', 'chcp 65001 >nul', 'set PYTHONUTF8=1', 'set PYTHONUNBUFFERED=1',
        "cd /d `"$Directory`"", "call $Command 1>`"$stdout`" 2>`"$stderr`" <nul")
    [IO.File]::WriteAllLines($wrapper, $lines, [Text.UTF8Encoding]::new($false))
    # Windows 的独立隐藏进程不依附启动器终端；输出直接写文件。
    $process = Start-Process -FilePath $env:ComSpec -ArgumentList "/d /s /c `"`"$wrapper`"`"" `
        -WorkingDirectory $Directory -WindowStyle Hidden -PassThru
    try {
        $record = [pscustomobject]@{
            name = $Name
            pid = $process.Id
            started = $process.StartTime.ToUniversalTime().Ticks.ToString()
        }
        $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RuntimeDir "$Name.json") -Encoding UTF8
        return $record
    } catch {
        if (-not $process.HasExited) { & taskkill.exe /PID $process.Id /T /F | Out-Null }
        throw
    }
}

function Stop-HausService($Record) {
    if (Get-OwnedProcess $Record) {
        & taskkill.exe /PID $Record.pid /T /F | Out-Null
        if ($LASTEXITCODE -ne 0 -and (Get-OwnedProcess $Record)) {
            throw "无法停止 $($Record.name)，请重试。"
        }
    }
    Remove-Item -LiteralPath (Join-Path $RuntimeDir "$($Record.name).json") -ErrorAction SilentlyContinue
}

function Assert-ServicesRunning($Records) {
    foreach ($record in $Records) {
        if (-not (Get-OwnedProcess $record)) {
            throw "$($record.name) 已退出，请查看 $RuntimeDir 中对应的日志。"
        }
    }
}

function Wait-HausUrl([string]$Url, $Records) {
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        Assert-ServicesRunning $Records
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw "服务等待超时：$Url，请查看 $RuntimeDir 中的日志。"
}

function Invoke-HausManager {
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
    $lock = $null
    $created = @()
    try {
        try {
            $lock = [IO.File]::Open((Join-Path $RuntimeDir 'manager.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
        } catch { throw '另一个启动或停止操作正在进行，请稍后重试。' }
        $records = @(Get-ServiceRecords)
        if ($Action -eq 'stop') {
            foreach ($record in $records) { Stop-HausService $record }
            Write-Host '已停止本启动器管理的全部服务。'
            return
        }
        if ($Action -eq 'status') {
            if (-not $records.Count) { Write-Host '没有本启动器管理的服务。' }
            foreach ($record in $records) {
                $status = if (Get-OwnedProcess $record) { '运行中' } else { '已退出' }
                Write-Host "$($record.name): $status"
            }
            return
        }

        $live = @($records | Where-Object { Get-OwnedProcess $_ })
        if ($live.Count) {
            if ($live.Count -ne 5) { throw '部分服务仍在运行，请先运行 stopHaus.bat，再重新启动。' }
            Wait-HausUrl 'http://127.0.0.1:8081/ready' $live
            Wait-HausUrl 'http://127.0.0.1:8080/' $live
            Write-Host '服务已经运行，本次没有重复启动。'
        } else {
            $listeners = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
            if (@($listeners | Where-Object { $_.Port -in 8080, 8081 }).Count) {
                throw '8080 或 8081 端口已被占用。若是旧版启动窗口，请先关闭旧版服务窗口，再启动。'
            }
            if (-not $env:PYTHON_CMD) { throw '请通过 startHaus.bat 启动，以自动选择 Python 环境。' }
            Push-Location $ProjectRoot
            try {
                if (-not (Test-Path 'frontend/node_modules')) {
                    & npm.cmd --prefix frontend install
                    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
                }
                Write-Host '[准备] 检查并升级数据库结构...'
                Push-Location (Join-Path $ProjectRoot 'backend')
                try {
                    & $env:ComSpec /d /s /c "`"$env:PYTHON_CMD -m alembic upgrade head`""
                    if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败，未启动任何服务。' }
                } finally { Pop-Location }
            } finally { Pop-Location }

            $services = @(
                @{ Name = 'api'; Directory = 'backend'; Command = "$env:PYTHON_CMD -m app.run_api --port 8081" },
                @{ Name = 'generation'; Directory = 'backend'; Command = "$env:PYTHON_CMD -m app.workers.generation_worker" },
                @{ Name = 'effect-render'; Directory = 'backend'; Command = "$env:PYTHON_CMD -m app.workers.effect_render_worker" },
                @{ Name = 'blender'; Directory = 'backend'; Command = "$env:PYTHON_CMD -m app.workers.blender_worker" },
                @{ Name = 'frontend'; Directory = 'frontend'; Command = 'npm run dev -- --port 8080 --strictPort' }
            )
            foreach ($service in $services) {
                Write-Host "[启动] $($service.Name)"
                $created += Start-HausService $service.Name (Join-Path $ProjectRoot $service.Directory) $service.Command
            }
            Wait-HausUrl 'http://127.0.0.1:8081/ready' $created
            Wait-HausUrl 'http://127.0.0.1:8080/' $created
            Assert-ServicesRunning $created
        }
        Write-Host "已启动完成！网页地址：http://127.0.0.1:8080"
        Write-Host "日志目录：$RuntimeDir"
        Write-Host '现在可以关闭此窗口，服务会继续在后台运行。停止服务请双击 stopHaus.bat。'
        try { Start-Process 'http://127.0.0.1:8080' } catch { Write-Host '浏览器未打开，请手动访问网页地址。' }
    } catch {
        $failure = $_
        foreach ($record in $created) {
            try { Stop-HausService $record } catch { Write-Warning $_ }
        }
        throw $failure
    } finally {
        if ($lock) { $lock.Dispose() }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try { Invoke-HausManager } catch { Write-Host "[失败] $_" -ForegroundColor Red; exit 1 }
}
