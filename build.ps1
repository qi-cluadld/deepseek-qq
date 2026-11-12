# 一键打包成单文件 exe：dist\deepseek-qq.exe
# 用法（PowerShell）：  .\build.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "==> 检查依赖" -ForegroundColor Cyan
python -c "import aiohttp, yaml" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "缺少依赖，正在安装..." -ForegroundColor Yellow
    python -m pip install -r requirements.txt
}

Write-Host "==> 清理旧产物" -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
Remove-Item -Force deepseek-qq.spec -ErrorAction SilentlyContinue

Write-Host "==> PyInstaller 打包（单文件，带控制台窗口）" -ForegroundColor Cyan
# --runtime-tmpdir "_rt"：解压到 exe 所在目录，避免系统 Temp 被安全策略/杀毒拦截
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name deepseek-qq `
    --runtime-tmpdir "_rt" `
    --add-data "config.example.yaml;." `
    --collect-submodules app `
    --hidden-import aiohttp `
    --hidden-import yaml `
    main.py

if ($LASTEXITCODE -ne 0) { throw "打包失败" }

# 把示例配置放到 exe 旁边，方便第一次运行
Copy-Item config.example.yaml dist\config.example.yaml -Force

Write-Host ""
Write-Host "==> 完成：dist\deepseek-qq.exe" -ForegroundColor Green
Write-Host "    复制 dist 里的 exe 到任意目录，首次运行会自动生成 config.yaml"
