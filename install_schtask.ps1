# Register CodexInternalProxy to run at user logon (no extra dependencies).
$taskName = "CodexInternalProxy"
$script   = Join-Path $PSScriptRoot "codex_proxy.py"

$action   = New-ScheduledTaskAction -Execute "pythonw.exe" -Argument "`"$script`"" -WorkingDirectory $PSScriptRoot
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Registered task '$taskName' (runs at user logon)"
Write-Host "  Start now:   Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  Remove:      Unregister-ScheduledTask -TaskName '$taskName'"