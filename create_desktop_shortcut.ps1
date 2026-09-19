$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$target = Join-Path $root 'launch_zhishen.bat'
$icon = Join-Path $root 'zhishen_alert.ico'
$shell = New-Object -ComObject WScript.Shell
$displayName = '個股三層轉強提醒.lnk'
$oldPath = Join-Path $desktop '智伸科4551三層轉強提醒.lnk'
$shortcutPath = Join-Path $desktop $displayName
if (Test-Path -LiteralPath $oldPath) {
  Remove-Item -LiteralPath $oldPath -Force
}
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = '個股三層轉強提醒'
$shortcut.Save()
Write-Output $shortcutPath
