param()

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$cesiumSourceDir = Join-Path $projectRoot 'node_modules\cesium\Build\Cesium'
$cesiumPublicDir = Join-Path $projectRoot 'public\cesium'
$staticDirs = @('Assets', 'ThirdParty', 'Workers', 'Widgets')

New-Item -ItemType Directory -Path $cesiumPublicDir -Force | Out-Null

foreach ($dir in $staticDirs) {
    Copy-Item `
        -LiteralPath (Join-Path $cesiumSourceDir $dir) `
        -Destination $cesiumPublicDir `
        -Recurse `
        -Force
}

Write-Output "Synced Cesium assets to $cesiumPublicDir"
