param(
    [string]$Exe = "$PSScriptRoot\..\dist\MyMusic\MyMusic.exe",
    [string]$Report = "$PSScriptRoot\..\docs\single-instance-report.json"
)

$dataDir = Join-Path $env:TEMP ("mymusic-single-" + [guid]::NewGuid().ToString("N"))
$first = Start-Process -FilePath $Exe -ArgumentList @("--data-dir", $dataDir) -PassThru
$deadline = (Get-Date).AddSeconds(15)
while ($first.MainWindowHandle -eq 0 -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 50
    $first.Refresh()
}

$second = Start-Process -FilePath $Exe -ArgumentList @("--data-dir", $dataDir) -PassThru
$secondExited = $second.WaitForExit(10000)
$first.Refresh()

$document = [pscustomobject]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    first_window_detected = ($first.MainWindowHandle -ne 0)
    first_alive_after_second_launch = (-not $first.HasExited)
    second_exited_within_10s = $secondExited
    second_exit_code = $(if ($secondExited) { $second.ExitCode } else { $null })
    two_independent_instances = (($secondExited -eq $false) -or ($first.HasExited))
}
$json = $document | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($Report, $json, (New-Object System.Text.UTF8Encoding($false)))
$json

try { Stop-Process -Id $first.Id -Force -ErrorAction Stop } catch { }
if (-not $secondExited) { try { Stop-Process -Id $second.Id -Force -ErrorAction Stop } catch { } }
Start-Sleep -Milliseconds 300
Remove-Item -LiteralPath $dataDir -Recurse -Force -ErrorAction SilentlyContinue
