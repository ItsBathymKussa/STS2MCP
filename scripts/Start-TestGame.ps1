<#
.SYNOPSIS
Launch an isolated game copy with a new, disposable test profile.
.DESCRIPTION
Requires the copy's override.cfg to enable a custom user directory. Copies
only settings/progress/preferences from an optional test template, never a run.
The game and STS2_MCP mod must already be installed in GameDir.
#>
param(
    [Parameter(Mandatory)][string]$GameDir,
    [Parameter(Mandatory)][string]$RunDirectory,
    [string]$TemplateUserDataRoot,
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'
$testGameDir = [IO.Path]::GetFullPath($GameDir)
$testRunDir = [IO.Path]::GetFullPath($RunDirectory)
$testOverride = Get-Content -LiteralPath (Join-Path $testGameDir 'override.cfg') -Raw
if ($testOverride -notmatch 'config/use_custom_user_dir\s*=\s*true' -or
    $testOverride -notmatch 'config/custom_user_dir_name\s*=\s*"([^"]+)"') {
    throw 'The test game must enable a custom user directory in override.cfg.'
}
$testUserName = $Matches[1]
if ($testUserName.Contains('/') -or $testUserName.Contains('\') -or $testUserName -in @('.', '..')) {
    throw 'Use a simple directory name for config/custom_user_dir_name.'
}
$testUserRoot = Join-Path $testRunDir 'user-data'
$testAccountDir = Join-Path (Join-Path $testUserRoot $testUserName) 'default/1'
if (Test-Path -LiteralPath (Join-Path $testAccountDir 'settings.save')) {
    throw 'RunDirectory already contains a test profile. Choose a new directory.'
}
New-Item -ItemType Directory -Path $testAccountDir -Force | Out-Null
$testSettings = @{
    schema_version = 8
    seen_ea_disclaimer = $true
    skip_intro_logo = $true
    fullscreen = $false
    language = 'zhs'
    mod_settings = @{mods_enabled = $true; mod_list = @()}
}
if ($TemplateUserDataRoot) {
    $testTemplateAccount = Join-Path ([IO.Path]::GetFullPath($TemplateUserDataRoot)) 'default/1'
    $testSettings = Get-Content -LiteralPath (Join-Path $testTemplateAccount 'settings.save') -Raw |
        ConvertFrom-Json -AsHashtable
    foreach ($testRelativeFile in @('profile.save', 'profile1/saves/prefs.save',
        'profile1/saves/progress.save', 'modded/profile.save',
        'modded/profile1/saves/prefs.save', 'modded/profile1/saves/progress.save')) {
        $testTemplateFile = Join-Path $testTemplateAccount $testRelativeFile
        if (Test-Path -LiteralPath $testTemplateFile) {
            $testDestination = Join-Path $testAccountDir $testRelativeFile
            New-Item -ItemType Directory -Path (Split-Path $testDestination) -Force | Out-Null
            Copy-Item -LiteralPath $testTemplateFile -Destination $testDestination
        }
    }
}
$testSettings.mod_settings.mods_enabled = $true
$testSettings.mod_settings.mod_list = @(
    Get-ChildItem -LiteralPath (Join-Path $testGameDir 'mods') -Filter '*.json' -Recurse |
        ForEach-Object {
            $testManifest = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
            if ($testManifest.id) {
                @{id = $testManifest.id; is_enabled = $true; source = 'mods_directory'}
            }
        }
)
$testSettings.skip_intro_logo = $true
$testSettings.fullscreen = $false
$testSettings | ConvertTo-Json -Depth 20 |
    Set-Content -LiteralPath (Join-Path $testAccountDir 'settings.save') -Encoding utf8
$testArgs = @('--force-steam=off', '--log-file', ('"' + (Join-Path $testRunDir 'game.log') + '"'))
if ($Headless) { $testArgs = @('--headless') + $testArgs }
$testProcess = Start-Process -FilePath (Join-Path $testGameDir 'SlayTheSpire2.exe') `
    -WorkingDirectory $testGameDir -ArgumentList $testArgs `
    -Environment @{APPDATA = $testUserRoot; LOCALAPPDATA = $testUserRoot} `
    -WindowStyle Hidden -PassThru
$testProcess.Id | Set-Content -LiteralPath (Join-Path $testRunDir 'game.pid')
[pscustomobject]@{ProcessId = $testProcess.Id; UserDataRoot = $testUserRoot; RunDirectory = $testRunDir}
