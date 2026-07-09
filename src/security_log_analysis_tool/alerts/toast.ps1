# toast.ps1 - Raise a native Windows toast for a security-log-analysis-tool alert.
#
# Ported from the personal toolkit's notify-desktop.ps1: same WinRT projection
# approach (Windows PowerShell only, no external module), trimmed to a single
# "info" style toast for finding-alert notifications.
#
# Implementation notes:
#   - Uses the WinRT projection available only in Windows PowerShell (powershell.exe):
#     [Windows.UI.Notifications.*, ..., ContentType = WindowsRuntime].
#   - Title / Body are XML-escaped before being placed into the toast payload.
#   - Wrapped in try/catch: a broken toast must NEVER fail the caller, so on any
#     error it prints a plain-text fallback line and ALWAYS exits 0.
#
# Usage:
#   .\toast.ps1 -Title "3 finding(s) - job abc123" -Body "[CRITICAL] multi-vector correlation"

param(
    [Parameter(Mandatory = $true)]
    [string]$Title,

    [Parameter(Mandatory = $true)]
    [string]$Body
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
  <audio src="ms-winsoundevent:Notification.Default"/>
</toast>
"@

    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]

    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($toastXml)

    $toast = New-Object Windows.UI.Notifications.ToastNotification $xml

    # PowerShell's own registered AUMID - gives the toast a real app identity.
    $aumid = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($toast)
}
catch {
    # A broken toast must never fail the caller. Fall back to a plain line, exit 0.
    Write-Host ("[toast] unavailable: {0} - {1}" -f $Title, $Body)
}

exit 0
