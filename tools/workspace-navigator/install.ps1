# Workspace Navigator — 安装脚本
# 将扩展复制到 VS Code 用户扩展目录，无需打包或发布

$srcDir = "$PSScriptRoot"
$destDir = "$env:USERPROFILE\.vscode\extensions\local.workspace-navigator-0.0.1"

Write-Host ""
Write-Host "=== Workspace Navigator 安装 ===" -ForegroundColor Cyan

# Remove old version if exists
if (Test-Path $destDir) {
    Write-Host "正在移除旧版本..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $destDir
}

# Copy extension files
Write-Host "正在安装到：$destDir" -ForegroundColor Green
Copy-Item -Recurse $srcDir $destDir

# Verify
if (Test-Path "$destDir\package.json") {
    Write-Host ""
    Write-Host "[OK] 安装成功！" -ForegroundColor Green
    Write-Host ""
    Write-Host "请在 VS Code 中执行：" -ForegroundColor Cyan
    Write-Host "  Ctrl+Shift+P → Developer: Reload Window" -ForegroundColor White
    Write-Host ""
    Write-Host "使用方式：" -ForegroundColor Cyan
    Write-Host "  快捷键：Ctrl+Alt+W（Mac: Cmd+Alt+W）" -ForegroundColor White
    Write-Host "  命令面板：Workspace: 定位到项目目录" -ForegroundColor White
    Write-Host ""
    Write-Host "如需修改快捷键：" -ForegroundColor Cyan
    Write-Host "  Ctrl+K Ctrl+S → 搜索 workspace-navigator.go → 修改绑定" -ForegroundColor White
} else {
    Write-Host "[FAIL] 安装失败，请检查源目录是否存在 package.json" -ForegroundColor Red
}
