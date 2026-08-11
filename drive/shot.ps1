# Capture the UMVC3 window to a PNG, downscaled so it is cheap to look at.
param([string]$Out = "$PSScriptRoot\shot.png", [int]$Width = 1280)

Add-Type -AssemblyName System.Drawing, System.Windows.Forms
if (-not ("Win32Shot" -as [type])) {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Shot {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
}
"@
}

$p = Get-Process umvc3 -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Error "umvc3 not running / no window"; exit 1 }

$r = New-Object Win32Shot+RECT
[void][Win32Shot]::GetWindowRect($p.MainWindowHandle, [ref]$r)
$w = $r.R - $r.L; $h = $r.B - $r.T
if ($w -le 0 -or $h -le 0) { Write-Error "bad window rect"; exit 1 }

$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$g.Dispose()

if ($Width -gt 0 -and $w -gt $Width) {
  $nh = [int]($h * $Width / $w)
  $small = New-Object System.Drawing.Bitmap($Width, $nh)
  $g2 = [System.Drawing.Graphics]::FromImage($small)
  $g2.InterpolationMode = 'HighQualityBicubic'
  $g2.DrawImage($bmp, 0, 0, $Width, $nh)
  $g2.Dispose(); $bmp.Dispose(); $bmp = $small
}

$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
"{0}  ({1}x{2} window)" -f $Out, $w, $h
