# Verify decode->encode of vertex positions is lossless for every vertex.
param([Parameter(Mandatory=$true)][string]$Path)

$b = [System.IO.File]::ReadAllBytes($Path)
$meshCount = [BitConverter]::ToUInt16($b,8)
$meshOff   = [int][BitConverter]::ToUInt64($b,0x40)
$vtxOff    = [int][BitConverter]::ToUInt64($b,0x48)

[double]$minX = [BitConverter]::ToSingle($b,0x70); [double]$maxX = [BitConverter]::ToSingle($b,0x80)
[double]$minY = [BitConverter]::ToSingle($b,0x74); [double]$maxY = [BitConverter]::ToSingle($b,0x84)
[double]$minZ = [BitConverter]::ToSingle($b,0x78); [double]$maxZ = [BitConverter]::ToSingle($b,0x88)
[double]$exX = $maxX - $minX
[double]$exY = $maxY - $minY
[double]$exZ = $maxZ - $minZ
$mn = @($minX, $minY, $minZ)
$ex = @($exX, $exY, $exZ)
$S  = 32767.0

$tested = 0; $bad = 0; $maxErr = 0.0
$seen = @{}
for ($i=0; $i -lt $meshCount; $i++) {
    $o = $meshOff + $i*56
    $stride = [int]$b[$o+10]
    $vbo    = [int][BitConverter]::ToUInt32($b,$o+16)
    $lo     = [int][BitConverter]::ToUInt16($b,$o+40)
    $hi     = [int][BitConverter]::ToUInt16($b,$o+42)
    for ($v=$lo; $v -le $hi; $v++) {
        $key = "$vbo/$v"
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $vo = $vtxOff + $vbo + $v*$stride
        for ($a=0; $a -lt 3; $a++) {
            $raw = [int][BitConverter]::ToUInt16($b, $vo + $a*2)
            $pos = $mn[$a] + ($raw / $S) * $ex[$a]              # decode
            $re  = [int][Math]::Round((($pos - $mn[$a]) / $ex[$a]) * $S)   # encode
            $tested++
            if ($re -ne $raw) {
                $bad++
                $d = [Math]::Abs($re - $raw)
                if ($d -gt $maxErr) { $maxErr = $d }
            }
        }
    }
}
Write-Output "components tested : $tested"
Write-Output "mismatches        : $bad"
Write-Output "max raw deviation : $maxErr"
Write-Output "LOSSLESS: $($bad -eq 0)"
