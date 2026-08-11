# Send keystrokes to the UMVC3 window via SendInput with hardware scan codes.
# Posted messages (SendKeys) are ignored by DirectInput; scan codes are not.
# Usage: key.ps1 Left Left Down    (repeats allowed, ~90ms apart)
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Keys)

if (-not ("Win32Key" -as [type])) {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Key {
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT {
    public ushort wVk, wScan; public uint dwFlags, time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT {
    public uint type; public KEYBDINPUT ki; public int pad1, pad2; }
  [DllImport("user32.dll")] public static extern uint SendInput(uint n, INPUT[] p, int size);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();

  const uint SCANCODE = 0x0008, KEYUP = 0x0002, EXTENDED = 0x0001;
  public static void Tap(ushort scan, bool extended) {
    uint f = SCANCODE | (extended ? EXTENDED : 0);
    INPUT[] a = new INPUT[2];
    a[0].type = 1; a[0].ki.wScan = scan; a[0].ki.dwFlags = f;
    a[1].type = 1; a[1].ki.wScan = scan; a[1].ki.dwFlags = f | KEYUP;
    SendInput(1, new INPUT[]{a[0]}, Marshal.SizeOf(typeof(INPUT)));
    System.Threading.Thread.Sleep(40);
    SendInput(1, new INPUT[]{a[1]}, Marshal.SizeOf(typeof(INPUT)));
  }
}
"@
}

$map = @{
  'Left'  = @(0x4B, $true);  'Right' = @(0x4D, $true)
  'Up'    = @(0x48, $true);  'Down'  = @(0x50, $true)
  'Enter' = @(0x1C, $false); 'Esc'   = @(0x01, $false)
  'Ctrl'  = @(0x1D, $false); 'Back'  = @(0x0E, $false)
}

$p = Get-Process umvc3 -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Error "umvc3 not running"; exit 1 }
[void][Win32Key]::SetForegroundWindow($p.MainWindowHandle)
Start-Sleep -Milliseconds 250
if ([Win32Key]::GetForegroundWindow() -ne $p.MainWindowHandle) {
  Write-Warning "game window did not take focus; input may go elsewhere"
}

foreach ($k in $Keys) {
  if (-not $map.ContainsKey($k)) { Write-Error "unknown key '$k'"; exit 1 }
  [Win32Key]::Tap($map[$k][0], $map[$k][1])
  Start-Sleep -Milliseconds 90
}
"sent: $($Keys -join ' ')"
