# Read-only inspection. No Resolve settings are changed.
param([string]$DeveloperFolder = '')
$ErrorActionPreference = 'Stop'
$candidates = @()
if ($DeveloperFolder) { $candidates += $DeveloperFolder }
$candidates += Join-Path $env:ProgramData 'Blackmagic Design\DaVinci Resolve\Support\Developer'
$candidates += Join-Path $env:ProgramFiles 'Blackmagic Design\DaVinci Resolve\Developer'
$found = @($candidates | Where-Object { Test-Path -LiteralPath $_ })
Write-Output 'Resolve documentation inspection'
Write-Output 'No settings are changed.'
$exe = Join-Path $env:ProgramFiles 'Blackmagic Design\DaVinci Resolve\Resolve.exe'
if (Test-Path -LiteralPath $exe) { Write-Output (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion }
if ($found.Count -eq 0) {
    Write-Output 'Developer folder not found.'
    Write-Output 'Use Help > Documentation > Developer.'
    Write-Output 'Run again with -DeveloperFolder.'
    exit 1
}
foreach ($folder in $found) {
    Get-ChildItem -LiteralPath $folder -Recurse -File |
      Where-Object { $_.Name -match 'readme|scripting.*\.(txt|md|html)$' } |
      ForEach-Object {
        $sdkMatches = Select-String -LiteralPath $_.FullName -Pattern 'Fairlight|Equaliz|Dynamics|VoiceIsolation|AudioEffect|AudioPlugin' -Context 1,2
        if ($sdkMatches) { Write-Output $_.FullName; $sdkMatches | ForEach-Object { Write-Output $_.ToString() } }
      }
}
Write-Output 'Matches are documentation evidence only.'
Write-Output 'They do not verify host behavior.'
