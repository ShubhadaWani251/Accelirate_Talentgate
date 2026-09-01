<#
.SYNOPSIS
    Registers TalentGate's housekeeping jobs with Windows Task Scheduler.

.DESCRIPTION
    The same two jobs as deploy/crontab.example, for a Windows host running the app directly
    rather than in a container. Neither is optional:

      finalize_expired_attempts - without it, exam attempts abandoned mid-way stay
                                  in_progress forever and are never scored.
      process_email_queue       - without it, invitation emails are never sent AT ALL.
                                  Creating an Invitation only queues it; this command is the
                                  only thing that actually sends one - not a backup job, the
                                  entire pipeline. Registered every 1 minute for exactly that
                                  reason. -MultipleInstances IgnoreNew below is what stops a
                                  run still working through a large batch from overlapping
                                  the next minute's tick.

    Draft batches are NOT auto-deleted - that 24-hour expiry job (delete_expired_draft_batches)
    was removed. A Draft now sits until a TA/admin deletes it explicitly from the Drafts list.
    This script unregisters that old task if a previous run of this script left it behind.

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
    @{ Name = 'TalentGate-ProcessEmailQueue'; Command = 'process_email_queue'; Minutes = 1 }
)

# Removes the task a previous run of this script may have registered for the now-removed
# draft-batch auto-expiry job, so it doesn't keep running (and logging failures) forever.
$staleTask = Get-ScheduledTask -TaskName 'TalentGate-DeleteExpiredDraftBatches' -ErrorAction SilentlyContinue
if ($staleTask) {
    Write-Host 'Removing stale task TalentGate-DeleteExpiredDraftBatches (auto-expiry was removed)...'
    Unregister-ScheduledTask -TaskName 'TalentGate-DeleteExpiredDraftBatches' -Confirm:$false
}

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
