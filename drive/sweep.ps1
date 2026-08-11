# Step the CSS cursor and stack the name plate from each stop into one image,
# so a whole row or column can be read in a single look.
# Usage: sweep.ps1 -Key Right -Count 4 -Out row.png
param([string]$Key = 'Right', [int]$Count = 4, [string]$Out, [switch]$First)

$SP = $PSScriptRoot
Add-Type -AssemblyName System.Drawing
if (-not ("Win32Sweep" -as [type])) {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Sweep {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
}
"@
}

# Name plate region within the window, and the grid, in window pixels.
$NAME = New-Object System.Drawing.Rectangle(115, 380, 200, 48)

function Grab {
  $p = Get-Process umvc3 | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
  $r = New-Object Win32Sweep+RECT
  [void][Win32Sweep]::GetWindowRect($p.MainWindowHandle, [ref]$r)
  $b = New-Object System.Drawing.Bitmap(($r.R - $r.L), ($r.B - $r.T))
  $g = [System.Drawing.Graphics]::FromImage($b)
  $g.CopyFromScreen($r.L, $r.T, 0, 0, $b.Size)
  $g.Dispose()
  return $b
}

$frames = @()
if ($First) { $frames += (Grab) }
for ($i = 0; $i -lt $Count; $i++) {
  & "$SP\key.ps1" $Key | Out-Null
  Start-Sleep -Milliseconds 350
  $frames += (Grab)
}

$zoom = 2.5
$cw = [int]($NAME.Width * $zoom); $ch = [int]($NAME.Height * $zoom)
$sheet = New-Object System.Drawing.Bitmap($cw, ($ch * $frames.Count))
$gs = [System.Drawing.Graphics]::FromImage($sheet)
$gs.InterpolationMode = 'HighQualityBicubic'
for ($i = 0; $i -lt $frames.Count; $i++) {
  $dst = New-Object System.Drawing.Rectangle(0, ($i * $ch), $cw, $ch)
  $gs.DrawImage($frames[$i], $dst, $NAME, 'Pixel')
  $frames[$i].Dispose()
}
$gs.Dispose()
$sheet.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$sheet.Dispose()
"$Out  ($($frames.Count) stops, top to bottom)"
