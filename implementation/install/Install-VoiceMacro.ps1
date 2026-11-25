param([switch]$WorkflowOnly)

$ErrorActionPreference = 'Stop'
$package = Split-Path -Parent $PSScriptRoot
$pluginId = 'com.sourovdeb.voicemacro'
$pluginSource = Join-Path $PSScriptRoot $pluginId
$supportPath = 'Blackmagic Design\DaVinci Resolve\Support'

function Install-WorkflowLauncher {
    $pluginRoot = Join-Path (Join-Path $env:ProgramData $supportPath) 'Workflow Integration Plugins'
    $destination = Join-Path $pluginRoot $pluginId
    $null = New-Item -ItemType Directory -Path $destination -Force
    foreach ($name in @('manifest.xml', 'main.js', 'package.json')) {
        Copy-Item -LiteralPath (Join-Path $pluginSource $name) -Destination (Join-Path $destination $name) -Force
    }
}

try {
    if ($WorkflowOnly) {
        Install-WorkflowLauncher
        exit 0
    }

    $localRoot = Join-Path $env:LOCALAPPDATA 'VoiceMacro'
    $app = Join-Path $localRoot 'App'
    if (Get-Process -Name VoiceMacro -ErrorAction SilentlyContinue) {
        throw 'Close VoiceMacro before installing.'
    }
    $runtime = @('VoiceMacro.exe', 'VoiceMacro.exe.config', 'START-HERE.html', 'voice_macro_console.py', 'Run-VoiceMacro.cmd')
    foreach ($name in ($runtime + @('matcher\match_voice.py', 'install\VoiceMacro.lua', 'install\Install-Matcher-Tools.cmd'))) {
        if (-not (Test-Path -LiteralPath (Join-Path $package $name) -PathType Leaf)) {
            throw "File missing: $name. Extract the whole ZIP before installing."
        }
    }
    $null = New-Item -ItemType Directory -Path $app -Force
    foreach ($name in $runtime) {
        Copy-Item -LiteralPath (Join-Path $package $name) -Destination (Join-Path $app $name) -Force
    }
    $matcher = Join-Path $app 'matcher'
    $null = New-Item -ItemType Directory -Path $matcher -Force
    Copy-Item -LiteralPath (Join-Path $package 'matcher\match_voice.py') -Destination $matcher -Force
    $utilities = Join-Path $app 'install'
    $null = New-Item -ItemType Directory -Path $utilities -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Install-Matcher-Tools.cmd') -Destination $utilities -Force
    if (Test-Path -LiteralPath (Join-Path $package 'presets') -PathType Container) {
        $presets = Join-Path $app 'presets'
        $null = New-Item -ItemType Directory -Path $presets -Force
        foreach ($name in @('Voice.json', 'Narration.json', 'Radio.json')) {
            $source = Join-Path $package ('presets\' + $name)
            if (Test-Path -LiteralPath $source -PathType Leaf) {
                Copy-Item -LiteralPath $source -Destination (Join-Path $presets $name) -Force
            }
        }
    }
    $personalProfile = Join-Path $localRoot 'Reference-Profile.json'
    $includedProfile = Join-Path $package 'presets\Zoom-H1n-Voice-Reference.json'
    if ((Test-Path -LiteralPath $includedProfile -PathType Leaf) -and -not (Test-Path -LiteralPath $personalProfile)) {
        Copy-Item -LiteralPath $includedProfile -Destination $personalProfile
    }

    $utility = Join-Path (Join-Path $env:APPDATA $supportPath) 'Fusion\Scripts\Utility'
    $null = New-Item -ItemType Directory -Path $utility -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'VoiceMacro.lua') -Destination (Join-Path $utility 'VoiceMacro.lua') -Force
    Write-Host "Installed VoiceMacro to $app"

    try {
        try { Install-WorkflowLauncher }
        catch [System.UnauthorizedAccessException] {
            Write-Host 'Allow the Windows prompt to install the Workflow Integrations menu entry.'
            $escapedPath = $PSCommandPath.Replace("'", "''")
            $command = "& '$escapedPath' -WorkflowOnly"
            $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
            $installer = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
                '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded
            ) -Wait -PassThru
            if ($installer.ExitCode -ne 0) { throw 'Workflow launcher installation failed.' }
        }
        Write-Host 'Restart Resolve Studio. Open Workspace > Workflow Integrations > VoiceMacro.'
    }
    catch {
        Write-Host ('Workflow launcher unavailable. ' + $_.Exception.Message)
        Write-Host 'Restart Resolve. Try Workspace > Scripts > VoiceMacro instead.'
        exit 2
    }
    Write-Host 'Workspace > Scripts also has a VoiceMacro launcher.'
}
catch {
    Write-Host $_.Exception.Message
    exit 1
}
