# notify-desktop.ps1 - Raise a native Windows toast from Windows PowerShell 5.1 (no BurntToast).
#
# Used by the orchestration layer (complete-session.ps1, the input-needed hook) to surface
# per-session completion, failure, ALL-DONE, and input-needed events in the Action Center.
#
# Implementation notes:
#   - Uses the WinRT projection available only in Windows PowerShell (powershell.exe), never pwsh:
#     [Windows.UI.Notifications.*, ..., ContentType = WindowsRuntime]. There is no external module.
#   - Toasts are shown under PowerShell's own registered AUMID (Start-menu shortcut GUID) so the
#     banner has a real app identity and lands in the Action Center reliably.
#   - Title / Body are XML-escaped before being placed into the toast payload.
#   - -Kind selects a distinct notification sound (alldone and failed each get their own).
#   - The entire body is wrapped in try/catch: a broken toast must NEVER fail a caller, so on any
#     error it prints a plain-text fallback line and the script ALWAYS exits 0.
#
# Usage:
#   .\notify-desktop.ps1 -Kind done    -Title "session-1 done"   -Body "commit abc123"
#   .\notify-desktop.ps1 -Kind failed  -Title "session-2 failed" -Body "DoD not met"
#   .\notify-desktop.ps1 -Kind alldone -Title "All sessions done" -Body "5/5 complete"
#   .\notify-desktop.ps1 -Kind input   -Title "Input needed"     -Body "approve write?"
#   .\notify-desktop.ps1 -Kind info    -Title "Note"             -Body "..." -Quiet

param(
    [Parameter(Mandatory = $true)]
    [string]$Title,

    [Parameter(Mandatory = $true)]
    [string]$Body,

    [ValidateSet('done', 'failed', 'alldone', 'input', 'info')]
    [string]$Kind = 'info',

    [switch]$Quiet
)

function Convert-XmlText {
    param([string]$Text)
    if ($null -eq $Text) { return '' }
    $t = $Text -replace '&', '&amp;'
    $t = $t -replace '<', '&lt;'
    $t = $t -replace '>', '&gt;'
    $t = $t -replace '"', '&quot;'
    $t = $t -replace "'", '&apos;'
    return $t
}

try {
    # Distinct sound per kind. alldone and failed are deliberately different from the default.
    $soundMap = @{
        'done'    = 'ms-winsoundevent:Notification.Default'
        'failed'  = 'ms-winsoundevent:Notification.Looping.Call'
        'alldone' = 'ms-winsoundevent:Notification.Looping.Alarm2'
        'input'   = 'ms-winsoundevent:Notification.IM'
        'info'    = 'ms-winsoundevent:Notification.Default'
    }
    $sound = $soundMap[$Kind]

    if ($Quiet) {
        $audioXml = '<audio silent="true"/>'
    }
    else {
        $audioXml = '<audio src="' + $sound + '"/>'
    }

    $titleX = Convert-XmlText $Title
    $bodyX = Convert-XmlText $Body

    $toastXml = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>$titleX</text>
      <text>$bodyX</text>
    </binding>
  </visual>
  $audioXml
</toast>
"@

    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]

    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($toastXml)

    $toast = New-Object Windows.UI.Notifications.ToastNotification $xml

    # PowerShell's own registered AUMID - gives the toast a real app identity in the Action Center.
    $aumid = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($toast)
}
catch {
    # A broken toast must never fail a caller. Fall back to a plain line and still exit 0.
    Write-Host ("[notify-desktop] toast unavailable ({0}): {1} - {2}" -f $Kind, $Title, $Body)
}

exit 0
