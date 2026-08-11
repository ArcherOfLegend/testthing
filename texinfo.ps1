# Decode MT Framework .tex headers and infer the pixel format from data size.
param([Parameter(Mandatory=$true)][string]$Root)

Write-Output ("{0,-46} {1,5}x{2,-5} {3,4} {4,10} {5,9} {6,8}  {7}" -f 'file','w','h','mip','dataBytes','bitsPerPx','fmtCode','guess')
Get-ChildItem $Root -Recurse -Filter *.tex | ForEach-Object {
    $b = [System.IO.File]::ReadAllBytes($_.FullName)
    if ($b.Length -lt 24 -or [System.Text.Encoding]::ASCII.GetString($b,0,3) -ne 'TEX') { return }

    $w1  = [BitConverter]::ToUInt32($b,4)
    $ver = $w1 -band 0xFFF
    $w2  = [BitConverter]::ToUInt32($b,8)
    $mip = [int]($w2 -band 0x3F)
    $wid = [int](($w2 -shr 6)  -band 0x1FFF)
    $hei = [int](($w2 -shr 19) -band 0x1FFF)
    $w3  = [BitConverter]::ToUInt32($b,12)
    $fmt = [int](($w3 -shr 8) -band 0xFF)

    $data = $b.Length - 24
    $px = $wid * $hei
    $bpp = if ($px -gt 0) { [Math]::Round(($data * 8.0) / $px, 3) } else { 0 }

    # a single-mip BC1 surface is 0.5 bytes/px (4 bpp); BC3/BC5 is 1.0 (8 bpp)
    $guess = switch ($bpp) {
        { $_ -ge 3.8 -and $_ -le 4.2 } { 'DXT1 (BC1)'; break }
        { $_ -ge 7.8 -and $_ -le 8.2 } { 'DXT5 (BC3)'; break }
        { $_ -ge 31  -and $_ -le 33  } { 'RGBA8'; break }
        default { '?' }
    }
    Write-Output ("{0,-46} {1,5}x{2,-5} {3,4} {4,10} {5,9} {6,8}  {7}" -f `
        $_.Name, $wid, $hei, $mip, $data, $bpp, $fmt, $guess)
}
