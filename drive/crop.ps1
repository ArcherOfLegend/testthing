# Capture the UMVC3 window and crop a region of it, optionally magnified.
# Coordinates are in window pixels (the window is ~1296x759).
param([string]$Out, [int]$X, [int]$Y, [int]$W, [int]$H, [double]$Zoom = 2.0)

Add-Type -AssemblyName System.Drawing, System.Windows.Forms
if (-not ("Win32Crop" -as [type])) {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Crop {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
}
"@
}

$p = Get-Process umvc3 -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Error "umvc3 not running"; exit 1 }
$r = New-Object Win32Crop+RECT
[void][Win32Crop]::GetWindowRect($p.MainWindowHandle, [ref]$r)

$full = New-Object System.Drawing.Bitmap(($r.R - $r.L), ($r.B - $r.T))
$g = [System.Drawing.Graphics]::FromImage($full)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $full.Size)
$g.Dispose()

$src = New-Object System.Drawing.Rectangle($X, $Y, $W, $H)
$dw = [int]($W * $Zoom); $dh = [int]($H * $Zoom)
$dst = New-Object System.Drawing.Bitmap($dw, $dh)
$g2 = [System.Drawing.Graphics]::FromImage($dst)
$g2.InterpolationMode = 'HighQualityBicubic'
$g2.DrawImage($full, (New-Object System.Drawing.Rectangle(0, 0, $dw, $dh)), $src, 'Pixel')
$g2.Dispose()
$dst.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$dst.Dispose(); $full.Dispose()
"$Out  ($dw x $dh)"
