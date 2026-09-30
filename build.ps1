<#
  逐字自动输入 · 一键打包脚本

  用法（在本仓库根目录执行）：
      powershell -ExecutionPolicy Bypass -File build.ps1

  产物（生成在 dist/ 目录）：
      逐字自动输入_vX.Y.Z.exe            单文件版
      逐字自动输入_vX.Y.Z_便携版.zip      目录版（启动更快）
      逐字自动输入_源码_vX.Y.Z.py         源码副本
      SHA256.txt                          校验值

  依赖：Python 3.10+（脚本会自动安装 PyInstaller）
#>

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location -LiteralPath $root

$srcFile = Join-Path $root "src\逐字自动输入.py"
$icon = Join-Path $root "assets\app.ico"
$versionFile = Join-Path $root "assets\version_info.txt"

if (-not (Test-Path -LiteralPath $srcFile)) { throw "找不到源码：$srcFile" }
if (-not (Test-Path -LiteralPath $icon)) { throw "找不到图标：$icon" }

# 从源码里读版本号，避免手写不一致
$raw = Get-Content -LiteralPath $srcFile -Raw -Encoding UTF8
$version = ([regex]::Match($raw, 'APP_VERSION\s*=\s*"([^"]+)"')).Groups[1].Value
$author = ([regex]::Match($raw, 'APP_AUTHOR\s*=\s*"([^"]+)"')).Groups[1].Value
if (-not $version) { throw "未能从源码读取 APP_VERSION" }

Write-Host "== 逐字自动输入 v$version（作者：$author）==" -ForegroundColor Cyan

Write-Host "[1/4] 安装/更新 PyInstaller ..." -ForegroundColor Gray
python -m pip install --upgrade --quiet pyinstaller

Write-Host "[2/4] 清理旧的构建产物 ..." -ForegroundColor Gray
foreach ($dir in @("$root\build", "$root\dist")) {
    if (Test-Path -LiteralPath $dir) { Remove-Item -LiteralPath $dir -Recurse -Force }
}

$commonArgs = @(
    "--noconfirm", "--clean", "--windowed",
    "--icon", $icon,
    "--add-data", "$icon;.",
    "--version-file", $versionFile,
    $srcFile
)

Write-Host "[3/4] 打包单文件版 + 便携版（第一次会慢一些）..." -ForegroundColor Gray
python -m PyInstaller @commonArgs --onefile `
    --name "逐字自动输入_v$version" `
    --distpath "$root\dist" --workpath "$root\build" --specpath "$root\build"

python -m PyInstaller @commonArgs --onedir `
    --name "逐字自动输入_v${version}_便携版" `
    --distpath "$root\dist" --workpath "$root\build" --specpath "$root\build"

Copy-Item -LiteralPath $srcFile -Destination "$root\dist\逐字自动输入_源码_v$version.py" -Force
Compress-Archive -Path "$root\dist\逐字自动输入_v${version}_便携版" `
                 -DestinationPath "$root\dist\逐字自动输入_v${version}_便携版.zip" -Force

Write-Host "[4/4] 生成 SHA256 校验值 ..." -ForegroundColor Gray
$lines = Get-ChildItem -LiteralPath "$root\dist" -File |
    Where-Object { $_.Name -ne "SHA256.txt" } |
    Sort-Object Name |
    ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()
        "$hash  $($_.Name)"
    }
$lines | Set-Content -LiteralPath "$root\dist\SHA256.txt" -Encoding UTF8

Write-Host ""
Write-Host "== 完成 ==" -ForegroundColor Green
Get-ChildItem -LiteralPath "$root\dist" | Select-Object Name, @{n = "大小"; e = {
        if ($_.PSIsContainer) { "<目录>" }
        elseif ($_.Length -gt 1MB) { "{0:N1} MB" -f ($_.Length / 1MB) }
        else { "{0:N1} KB" -f ($_.Length / 1KB) }
    } } | Format-Table -AutoSize
Write-Host "产物目录：$root\dist"
Write-Host "发布时请把 dist 里的 exe / zip / 源码 / SHA256.txt 上传到 Release。" -ForegroundColor Yellow
