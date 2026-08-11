param(
    [Parameter(Mandatory=$true)][string]$Path,
    [string]$Obj = $null
)

function Get-Half([uint16]$h) {
    $sign = if ($h -band 0x8000) { -1.0 } else { 1.0 }
    $exp  = ($h -shr 10) -band 0x1F
    $mant = $h -band 0x3FF
    if ($exp -eq 0)    { return $sign * [Math]::Pow(2,-14) * ($mant / 1024.0) }
    if ($exp -eq 0x1F) { return 0.0 }
    return $sign * [Math]::Pow(2, $exp - 15) * (1.0 + $mant / 1024.0)
}

$b = [System.IO.File]::ReadAllBytes($Path)

$version   = [BitConverter]::ToUInt16($b,4)
$boneCount = [BitConverter]::ToUInt16($b,6)
$meshCount = [BitConverter]::ToUInt16($b,8)
$matCount  = [BitConverter]::ToUInt16($b,10)
$vtxCount  = [BitConverter]::ToUInt32($b,12)
$idxCount  = [BitConverter]::ToUInt32($b,16)
$vtxBufSz  = [BitConverter]::ToUInt32($b,24)
$meshOff   = [BitConverter]::ToUInt64($b,0x40)
$vtxOff    = [BitConverter]::ToUInt64($b,0x48)
$idxOff    = [BitConverter]::ToUInt64($b,0x50)

[float]$minX = [BitConverter]::ToSingle($b,0x70)
[float]$minY = [BitConverter]::ToSingle($b,0x74)
[float]$minZ = [BitConverter]::ToSingle($b,0x78)
[float]$maxX = [BitConverter]::ToSingle($b,0x80)
[float]$maxY = [BitConverter]::ToSingle($b,0x84)
[float]$maxZ = [BitConverter]::ToSingle($b,0x88)
[float]$extX = $maxX - $minX
[float]$extY = $maxY - $minY
[float]$extZ = $maxZ - $minZ
$bbMin = @($minX,$minY,$minZ); $bbMax = @($maxX,$maxY,$maxZ); $ext = @($extX,$extY,$extZ)

Write-Output ("MOD v{0}  bones={1} meshes={2} mats={3} verts={4} idx={5}" -f $version,$boneCount,$meshCount,$matCount,$vtxCount,$idxCount)
Write-Output ("bbox min=({0:F2},{1:F2},{2:F2}) max=({3:F2},{4:F2},{5:F2})" -f $bbMin[0],$bbMin[1],$bbMin[2],$bbMax[0],$bbMax[1],$bbMax[2])

$MESH = 56
$meshes = @()
for ($i=0; $i -lt $meshCount; $i++) {
    $o = [int]$meshOff + $i*$MESH
    $meshes += [PSCustomObject]@{
        Index      = $i
        FmtId      = $b[$o+8]
        Stride     = [int]$b[$o+10]
        Flags      = ('{0:X2}' -f $b[$o+11])
        VtxStart   = [BitConverter]::ToUInt32($b,$o+12)
        VtxBufOff  = [BitConverter]::ToUInt32($b,$o+16)
        DeclHash   = ('{0:X8}' -f [BitConverter]::ToUInt32($b,$o+20))
        IdxStart   = [BitConverter]::ToUInt32($b,$o+24)
        IdxCount   = [BitConverter]::ToUInt32($b,$o+28)
        VtxLo      = [BitConverter]::ToUInt16($b,$o+40)
        VtxHi      = [BitConverter]::ToUInt16($b,$o+42)
    }
}

# report index ranges to determine whether indices are segment-absolute or mesh-relative
foreach ($m in $meshes) {
    $lo = [uint32]::MaxValue; $hi = 0
    for ($k=0; $k -lt $m.IdxCount; $k++) {
        $v = [BitConverter]::ToUInt16($b, [int]$idxOff + ($m.IdxStart + $k)*2)
        if ($v -lt $lo) { $lo = $v }
        if ($v -gt $hi) { $hi = $v }
    }
    Add-Member -InputObject $m -NotePropertyName IdxLo -NotePropertyValue $lo
    Add-Member -InputObject $m -NotePropertyName IdxHi -NotePropertyValue $hi
    Add-Member -InputObject $m -NotePropertyName NVerts -NotePropertyValue ($m.VtxHi - $m.VtxLo + 1)
}

$meshes | Format-Table Index,FmtId,Stride,VtxBufOff,VtxStart,VtxLo,VtxHi,NVerts,IdxStart,IdxCount,IdxLo,IdxHi,DeclHash -AutoSize | Out-String -Width 250 -Stream

if (-not $Obj) { return }

$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("# $([System.IO.Path]::GetFileName($Path)) -> OBJ")
$vBase = 1

foreach ($m in $meshes) {
    [void]$sb.AppendLine("g mesh$($m.Index)_fmt$($m.FmtId)_stride$($m.Stride)")

    $uvOff = switch ($m.Stride) { 40 { 24 } 24 { 16 } 28 { 20 } default { -1 } }

    # vertices for this mesh's range within its segment
    for ($vi = $m.VtxLo; $vi -le $m.VtxHi; $vi++) {
        $vo = [int]$vtxOff + [int]$m.VtxBufOff + $vi * [int]$m.Stride
        $px = [BitConverter]::ToUInt16($b,$vo)
        $py = [BitConverter]::ToUInt16($b,$vo+2)
        $pz = [BitConverter]::ToUInt16($b,$vo+4)
        $x = $bbMin[0] + ($px/32767.0)*$ext[0]
        $y = $bbMin[1] + ($py/32767.0)*$ext[1]
        $z = $bbMin[2] + ($pz/32767.0)*$ext[2]
        [void]$sb.AppendLine(("v {0:F4} {1:F4} {2:F4}" -f $x,$y,$z))
    }
    if ($uvOff -ge 0) {
        for ($vi = $m.VtxLo; $vi -le $m.VtxHi; $vi++) {
            $vo = [int]$vtxOff + [int]$m.VtxBufOff + $vi * [int]$m.Stride
            $u = Get-Half ([BitConverter]::ToUInt16($b,$vo+$uvOff))
            $vv = Get-Half ([BitConverter]::ToUInt16($b,$vo+$uvOff+2))
            [void]$sb.AppendLine(("vt {0:F5} {1:F5}" -f $u, (1.0 - $vv)))
        }
    }

    for ($k=0; $k -lt $m.IdxCount; $k += 3) {
        $i0 = [BitConverter]::ToUInt16($b, [int]$idxOff + ($m.IdxStart + $k)*2)
        $i1 = [BitConverter]::ToUInt16($b, [int]$idxOff + ($m.IdxStart + $k+1)*2)
        $i2 = [BitConverter]::ToUInt16($b, [int]$idxOff + ($m.IdxStart + $k+2)*2)
        if ($i0 -eq $i1 -or $i1 -eq $i2 -or $i0 -eq $i2) { continue }  # degenerate
        $a = $vBase + ($i0 - $m.VtxLo); $c2 = $vBase + ($i1 - $m.VtxLo); $c3 = $vBase + ($i2 - $m.VtxLo)
        if ($uvOff -ge 0) {
            [void]$sb.AppendLine("f $a/$a $c2/$c2 $c3/$c3")
        } else {
            [void]$sb.AppendLine("f $a $c2 $c3")
        }
    }
    $vBase += $m.NVerts
}

[System.IO.File]::WriteAllText($Obj, $sb.ToString())
Write-Output "wrote $Obj"
