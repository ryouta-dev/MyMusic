param(
    [string]$Exe = "$PSScriptRoot\..\dist\MyMusic\MyMusic.exe",
    [int]$Runs = 3,
    [string]$Report = "$PSScriptRoot\..\docs\startup-report.json"
)

$results = @()
for ($i = 1; $i -le $Runs; $i++) {
    $dataDir = Join-Path $env:TEMP ("mymusic-startup-" + [guid]::NewGuid().ToString("N"))
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process -FilePath $Exe -ArgumentList @("--data-dir", $dataDir) -PassThru
    $handle = 0
    while ($watch.Elapsed.TotalSeconds -lt 15) {
        $process.Refresh()
        $handle = $process.MainWindowHandle
        if ($handle -ne 0) { break }
        Start-Sleep -Milliseconds 25
    }
    $watch.Stop()
    $millis = if ($handle -ne 0) { [math]::Round($watch.Elapsed.TotalMilliseconds, 1) } else { $null }
    $results += [pscustomobject]@{
        run = $i
        interactive_ms = $millis
        window_detected = ($handle -ne 0)
    }
    try { Stop-Process -Id $process.Id -Force -ErrorAction Stop } catch { }
    Start-Sleep -Milliseconds 400
    Remove-Item -LiteralPath $dataDir -Recurse -Force -ErrorAction SilentlyContinue
}

$values = @($results | Where-Object { $_.interactive_ms } | ForEach-Object { $_.interactive_ms })
$sorted = @($values | Sort-Object)
$median = if ($sorted.Count -gt 0) {
    if ($sorted.Count % 2 -eq 1) { $sorted[[int](($sorted.Count - 1) / 2)] }
    else { [math]::Round(($sorted[$sorted.Count / 2 - 1] + $sorted[$sorted.Count / 2]) / 2, 1) }
} else { $null }

$document = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    exe = (Resolve-Path $Exe).Path
    runs = $results
    median_interactive_ms = $median
    note = "Process was force-stopped after the window appeared; this measures startup, not shutdown."
}
$json = $document | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($Report, $json, (New-Object System.Text.UTF8Encoding($false)))
$json
