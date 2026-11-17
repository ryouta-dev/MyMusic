param(
    [string]$Exe = "$PSScriptRoot\..\dist\MyMusic\MyMusic.exe",
    [string]$OutDir = "$PSScriptRoot\..\docs",
    [int]$Repeats = 3,
    [int]$IdleSeconds = 300,
    [int]$PlayingSeconds = 600,
    [int]$SearchSeconds = 120
)

$scenarios = @(
    [pscustomobject]@{ name = "idle-hidden"; mode = "idle"; seconds = $IdleSeconds; widget = $false },
    [pscustomobject]@{ name = "playing-widget"; mode = "playing"; seconds = $PlayingSeconds; widget = $true },
    [pscustomobject]@{ name = "playing-hidden"; mode = "playing"; seconds = $PlayingSeconds; widget = $false },
    [pscustomobject]@{ name = "search-open"; mode = "search"; seconds = $SearchSeconds; widget = $false }
)

$summary = @()
foreach ($scenario in $scenarios) {
    $runs = @()
    for ($repeat = 1; $repeat -le $Repeats; $repeat++) {
        $report = Join-Path $OutDir ("perf-" + $scenario.name + "-r" + $repeat + ".json")
        $arguments = @("--perf", $scenario.mode, "--perf-seconds", $scenario.seconds,
                       "--perf-report", $report)
        if ($scenario.widget) { $arguments += "--perf-widget" }
        $process = Start-Process -FilePath $Exe -ArgumentList $arguments -PassThru -Wait
        if ($process.ExitCode -ne 0) { Write-Warning ("run failed: " + $report) }
        if (Test-Path $report) {
            $data = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
            $runs += [pscustomobject]@{
                repeat = $repeat
                cpu_percent_avg = $data.cpu_percent_avg
                cpu_percent_p95 = $data.cpu_percent_p95
                private_mib_avg = $data.private_mib_avg
                private_mib_max = $data.private_mib_max
                private_mib_delta = $data.private_mib_delta
                playback_state = $data.playback_state
                playback_state_end = $data.playback_state_end
                tracks_played = $data.tracks_played
                auto_advances = $data.auto_advances
                search_state_end = $data.search_state_end
                gpu_percent_avg = $data.gpu_percent_avg
                report = (Split-Path $report -Leaf)
            }
        }
    }
    $cpuAvg = @($runs | ForEach-Object { $_.cpu_percent_avg } | Measure-Object -Average).Average
    $privateAvg = @($runs | ForEach-Object { $_.private_mib_avg } | Measure-Object -Average).Average
    $privateMax = @($runs | ForEach-Object { $_.private_mib_max } | Measure-Object -Maximum).Maximum
    $summary += [pscustomobject]@{
        scenario = $scenario.name
        mode = $scenario.mode
        widget_visible = $scenario.widget
        duration_s = $scenario.seconds
        repeats = $Repeats
        cpu_percent_avg_of_runs = $cpuAvg
        private_mib_avg_of_runs = $privateAvg
        private_mib_max = $privateMax
        tracks_played = @($runs | ForEach-Object { $_.tracks_played })
        runs = $runs
    }
}

$summaryPath = Join-Path $OutDir "perf-summary.json"
$json = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    exe = (Resolve-Path $Exe).Path
    protocol = "60 s warmup, $Repeats repeats, audio output muted at user request; CPU = process CPU delta / wall / logical cores * 100"
    scenarios = $summary
} | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($summaryPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Get-Content -LiteralPath $summaryPath -Raw
