param(
    [string]$Exe = "$PSScriptRoot\..\dist\MyMusic\MyMusic.exe",
    [string]$OutDir = "$PSScriptRoot\..\docs",
    [int]$Runs = 3,
    [double]$WorkloadSeconds = 20,
    [int]$PlayerSeconds = 240
)

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$workload = Join-Path $PSScriptRoot "bench_workload.py"
$playerReport = Join-Path $OutDir "perf-impact-player.json"
$results = @()

function Invoke-Workload {
    $raw = & $python $workload --seconds $WorkloadSeconds
    if ($LASTEXITCODE -ne 0) { throw "workload failed" }
    return $raw | ConvertFrom-Json
}

Write-Host "baseline: $Runs runs without player"
$baseline = @()
for ($i = 1; $i -le $Runs; $i++) {
    $value = Invoke-Workload
    $baseline += $value.iterations_per_second
    Write-Host ("  baseline {0}: {1:N1} it/s" -f $i, $value.iterations_per_second)
}

Write-Host "starting player (muted, both windows hidden)"
$arguments = @("--perf", "playing", "--perf-seconds", $PlayerSeconds,
               "--perf-warmup", "20", "--perf-report", $playerReport)
$player = Start-Process -FilePath $Exe -ArgumentList $arguments -PassThru
Start-Sleep -Seconds 25

$loaded = @()
for ($i = 1; $i -le $Runs; $i++) {
    $value = Invoke-Workload
    $loaded += $value.iterations_per_second
    Write-Host ("  with player {0}: {1:N1} it/s" -f $i, $value.iterations_per_second)
}

Wait-Process -Id $player.Id -Timeout ($PlayerSeconds + 180) -ErrorAction SilentlyContinue

function Get-Median($values) {
    $sorted = @($values | Sort-Object)
    $mid = [int][Math]::Floor($sorted.Count / 2)
    if ($sorted.Count % 2 -eq 0) {
        return ($sorted[$mid - 1] + $sorted[$mid]) / 2
    }
    return $sorted[$mid]
}

$baselineMedian = Get-Median $baseline
$loadedMedian = Get-Median $loaded
$degradation = (($baselineMedian - $loadedMedian) / $baselineMedian) * 100
$report = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    exe = (Resolve-Path $Exe).Path
    workload = "single-thread sha256 + integer loop, fixed $WorkloadSeconds s per run"
    runs = $Runs
    volume = 0
    baseline_iterations_per_second = $baseline
    loaded_iterations_per_second = $loaded
    baseline_median = [Math]::Round($baselineMedian, 1)
    loaded_median = [Math]::Round($loadedMedian, 1)
    degradation_percent = [Math]::Round($degradation, 2)
    target_percent = 2
    within_target = $degradation -le 2
    player_report = (Split-Path $playerReport -Leaf)
}
$path = Join-Path $OutDir "impact-report.json"
$json = $report | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding($false)))
Get-Content -LiteralPath $path -Raw
