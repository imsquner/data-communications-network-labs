param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not $CheckOnly) {
        $env:Path = 'C:\msys64\ucrt64\bin;' + $env:Path
        g++ -std=c++17 -O2 -Wall -Wextra -Wconversion -Werror lab1.cpp -o lab1.exe
        if ($LASTEXITCODE -ne 0) { throw 'C++ build failed' }
        Move-Item -LiteralPath 'lab1.exe' -Destination '验收/lab1.exe' -Force
        Push-Location '验收'
        try {
            & './lab1.exe' | Set-Content -LiteralPath 'run.log' -Encoding ascii
        } finally {
            Pop-Location
        }
        if ($LASTEXITCODE -ne 0) { throw 'Experiment failed' }
    }
    $log = Get-Content -LiteralPath '验收/run.log' -Raw
    foreach ($pattern in @('CRC reference: 0x4B37 PASS','CRC single-bit: 80/80 PASS','Hamming clean: 128/128 PASS','Hamming single-bit: 1408/1408 PASS')) {
        if (!$log.Contains($pattern)) { throw "Missing: $pattern" }
    }
    $rows = @(Import-Csv -LiteralPath '验收/statistics.csv')
    foreach ($scheme in @('CRC','Hamming')) {
        $group = @($rows | Where-Object scheme -eq $scheme)
        $maxBits = if ($scheme -eq 'CRC') { 10 } else { 11 }
        if (($group.bits -join ',') -ne ((0..$maxBits) -join ',')) { throw "Wrong range: $scheme" }
        foreach ($row in $group) {
            $total = [int]$row.clean + [int]$row.detected + [int]$row.undetected + [int]$row.corrected + [int]$row.miscorrected + [int]$row.rejected
            if ($total -ne 10000 -or [int]$row.trials -ne $total) { throw "Wrong total: $scheme $($row.bits)" }
        }
        if ([int]$group[0].clean -ne 10000) { throw "Clean check failed: $scheme" }
    }
    if ([int]$rows[1].detected -ne 10000 -or [int]$rows[12].corrected -ne 10000) { throw 'Single-bit check failed' }
    if (!($rows | Where-Object { $_.scheme -eq 'Hamming' -and [int]$_.miscorrected -gt 0 })) { throw 'No Hamming miscorrection case recorded' }
    'PASS: reference vector, 80 CRC single-bit cases, 128 clean Hamming cases, 1408 Hamming single-bit cases, 23 groups, 230000 trials'
} finally {
    Pop-Location
}

