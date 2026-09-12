Add-Type -Namespace Win32 -Name Win -MemberDefinition '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);'
$term = Get-Process -Id 20720 -ErrorAction SilentlyContinue
if ($term) { [Win32.Win]::ShowWindow($term.MainWindowHandle, 6) | Out-Null }
Start-Sleep -Milliseconds 500
$nw = Get-Process -Name NewWorld -ErrorAction SilentlyContinue | Select-Object -First 1
if ($nw) { [Win32.Win]::SetForegroundWindow($nw.MainWindowHandle) | Out-Null; 'nw-foreground' } else { 'no-nw' }
