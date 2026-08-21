<#
.SYNOPSIS
    Registers TalentGate's housekeeping jobs with Windows Task Scheduler.

.DESCRIPTION
    The same three jobs as deploy/crontab.example, for a Windows host running the app directly
    rather than in a container. None of them is optional:

      finalize_expired_attempts    - without it, exam attempts abandoned mid-way stay
                                     in_progress forever and are never scored.
      delete_expired_draft_batches - without it, Draft batches past their 24-hour window are
                                     never deleted. The app hides them and deletes lazily when
                                     someone opens one, but a draft nobody looks at again is
                                     only removed here.
      retry_stalled_invite_emails  - without it, an invitation email interrupted by a restart
                                     stays queued with nobody retrying it.

    Run from an elevated PowerShell prompt. Re-running replaces the existing tasks.

.PARAMETER BackendPath
    Path to the Backend directory (the one containing manage.py).

.PARAMETER RunAsUser
    Account to run the tasks under. Defaults to SYSTEM, which needs no stored password and
    survives the interactive user logging out. It must be able to read Backend\.env.

.EXAMPLE
    .\register-scheduled-tasks.ps1 -BackendPath C:\apps\talentgate\Backend
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackendPath,

    [string]$RunAsUser = 'SYSTEM'
)

$ErrorActionPreference = 'Stop'

$BackendPath = (Resolve-Path $BackendPath).Path
$python = Join-Path $BackendPath 'venv\Scripts\python.exe'

if (-not (Test-Path (Join-Path $BackendPath 'manage.py'))) {
    throw "No manage.py found in $BackendPath - is that the Backend directory?"
}
if (-not (Test-Path $python)) {
    throw "No interpreter at $python - create the virtualenv first."
}

# Interval is in minutes. Every command is idempotent and returns immediately when there is
# nothing to process, so running more often than strictly needed is safe.
$tasks = @(
    @{ Name = 'TalentGate-FinalizeExpiredAttempts'; Command = 'finalize_expired_attempts'; Minutes = 10 },
    @{ Name = 'TalentGate-DeleteExpiredDraftBatches'; Command = 'delete_expired_draft_batches'; Minutes = 30 },
    @{ Name = 'TalentGate-RetryStalledInviteEmails'; Command = 'retry_stalled_invite_emails'; Minutes = 15 }
)

foreach ($task in $tasks) {
    Write-Host "Registering $($task.Name) (every $($task.Minutes) min)..."

    $action = New-ScheduledTaskAction -Execute $python `
        -Argument "manage.py $($task.Command)" `
        -WorkingDirectory $BackendPath

    # RepetitionDuration of [TimeSpan]::MaxValue is how you express "repeat forever" here;
    # without it the repetition silently stops after the default one-day window.
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes $task.Minutes) `
        -RepetitionDuration ([TimeSpan]::MaxValue)

    $principal = New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType ServiceAccount -RunLevel Limited

    # StartWhenAvailable so a missed run (host asleep or rebooting) is caught up rather than
    # skipped. ExecutionTimeLimit caps a wedged run so it cannot block every later one.
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

    Register-ScheduledTask -TaskName $task.Name -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
}

Write-Host ''
Write-Host 'Registered. Verify with:'
Write-Host '  Get-ScheduledTask -TaskName "TalentGate-*" | Format-Table TaskName, State'
Write-Host 'Check last run results with:'
Write-Host '  Get-ScheduledTaskInfo -TaskName "TalentGate-FinalizeExpiredAttempts"'
