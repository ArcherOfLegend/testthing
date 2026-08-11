# Convert MT Framework .tex (rTexture) to .dds so Blender can load it.
# Header is 24 bytes, followed by raw BC-compressed surface data.
param(
    [Parameter(Mandatory=$true)][string]$Root,   # file or folder to convert
    [string]$Out = $null                          # output folder (default: alongside source)
)

function Convert-Tex([string]$path, [string]$dest) {
    $b = [System.IO.File]::ReadAllBytes($path)
    if ($b.Length -lt 24 -or [System.Text.Encoding]::ASCII.GetString($b,0,3) -ne 'TEX') {
        Write-Output "  skip (not TEX): $path"; return
    }
    $w2  = [BitConverter]::ToUInt32($b,8)
    $mip = [int]($w2 -band 0x3F)
    $wid = [int](($w2 -shr 6)  -band 0x1FFF)
    $hei = [int](($w2 -shr 19) -band 0x1FFF)
    $fmt = [int](([BitConverter]::ToUInt32($b,12) -shr 8) -band 0xFF)

    $data = $b.Length - 24
    if ($wid -le 0 -or $hei -le 0) { Write-Output "  skip (bad dims): $path"; return }
    $bpp = ($data * 8.0) / ($wid * $hei)

    # Prefer the measured bits-per-pixel; it is self-validating. fmtCode 19 is
    # BC1 in this build, 23/31/42 are BC3.
    if ($bpp -ge 3.5 -and $bpp -le 4.5)      { $fourCC = 'DXT1' }
    elseif ($bpp -ge 7.5 -and $bpp -le 8.5)  { $fourCC = 'DXT5' }
    elseif ($fmt -eq 19)                     { $fourCC = 'DXT1' }
    else                                     { $fourCC = 'DXT5' }

    $hdr = New-Object byte[] 128
    [Array]::Copy([System.Text.Encoding]::ASCII.GetBytes('DDS '), 0, $hdr, 0, 4)
    function PutU32([int]$off,[uint32]$v) { [Array]::Copy([BitConverter]::GetBytes($v),0,$hdr,$off,4) }
    PutU32 4   124                                   # dwSize
    PutU32 8   ([uint32]0x000A1007)                  # CAPS|HEIGHT|WIDTH|PIXELFORMAT|MIPMAPCOUNT|LINEARSIZE
    PutU32 12  ([uint32]$hei)
    PutU32 16  ([uint32]$wid)
    PutU32 20  ([uint32]$data)                       # linear size
    PutU32 24  0                                     # depth
    PutU32 28  ([uint32][Math]::Max(1,$mip))
    PutU32 76  32                                    # pixelformat size
    PutU32 80  4                                     # DDPF_FOURCC
    [Array]::Copy([System.Text.Encoding]::ASCII.GetBytes($fourCC), 0, $hdr, 84, 4)
    PutU32 108 ([uint32]0x1000)                      # DDSCAPS_TEXTURE

    $outBytes = New-Object byte[] (128 + $data)
    [Array]::Copy($hdr, 0, $outBytes, 0, 128)
    [Array]::Copy($b, 24, $outBytes, 128, $data)

    $dir = Split-Path $dest -Parent
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [System.IO.File]::WriteAllBytes($dest, $outBytes)
    Write-Output ("  {0,-46} {1,5}x{2,-5} {3}" -f (Split-Path $dest -Leaf), $wid, $hei, $fourCC)
}

if (Test-Path -LiteralPath $Root -PathType Leaf) {
    $dest = if ($Out) { Join-Path $Out ([System.IO.Path]::GetFileNameWithoutExtension($Root) + '.dds') }
            else { [System.IO.Path]::ChangeExtension($Root, '.dds') }
    Convert-Tex $Root $dest
} else {
    $base = (Resolve-Path $Root).Path
    Get-ChildItem $Root -Recurse -Filter *.tex | ForEach-Object {
        if ($Out) {
            $rel  = $_.FullName.Substring($base.Length).TrimStart('\','/')
            $dest = Join-Path $Out ([System.IO.Path]::ChangeExtension($rel,'.dds'))
        } else {
            $dest = [System.IO.Path]::ChangeExtension($_.FullName,'.dds')
        }
        Convert-Tex $_.FullName $dest
    }
}
