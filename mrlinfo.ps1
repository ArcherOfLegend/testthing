param([Parameter(Mandatory=$true)][string]$Path)

$b = [System.IO.File]::ReadAllBytes($Path)
if ([System.Text.Encoding]::ASCII.GetString($b,0,3) -ne 'MRL') { throw "not MRL" }
$version  = [BitConverter]::ToUInt32($b,4)
$matCount = [BitConverter]::ToUInt32($b,8)
$texCount = [BitConverter]::ToUInt32($b,12)
$texOff   = [int][BitConverter]::ToUInt64($b,24)
$matOff   = [int][BitConverter]::ToUInt64($b,32)
Write-Output ("MRL v{0}  materials={1} textures={2}  texOff=0x{3:X} matOff=0x{4:X}" -f $version,$matCount,$texCount,$texOff,$matOff)

$TEX_ENTRY = 88
Write-Output ""
Write-Output "--- textures ---"
$texNames = @()
for ($i=0; $i -lt $texCount; $i++) {
    $o = $texOff + $i*$TEX_ENTRY
    $nb = $b[($o+24)..($o+24+63)]
    $nul = [Array]::IndexOf($nb,[byte]0); if ($nul -lt 0){$nul=64}
    $name = [System.Text.Encoding]::ASCII.GetString($nb,0,$nul)
    $texNames += $name
    Write-Output ("  [{0}] {1}" -f $i, $name)
}

$MAT_ENTRY = 72
Write-Output ""
Write-Output "--- materials ---"
for ($i=0; $i -lt $matCount; $i++) {
    $o = $matOff + $i*$MAT_ENTRY
    $nameHash = [BitConverter]::ToUInt32($b,$o+8)
    $blkSize  = [BitConverter]::ToUInt32($b,$o+12)
    $f30      = [BitConverter]::ToUInt16($b,$o+30)
    $paramOff = [BitConverter]::ToUInt32($b,$o+56)
    $texIdx   = [int]($f30 / 32) - 1
    $tn = if ($texIdx -ge 0 -and $texIdx -lt $texCount) { $texNames[$texIdx] } else { "<out of range>" }
    Write-Output ("  [{0}] hash={1:X8} blk={2,5} +28=0x{3:X4} +30=0x{4:X4} (/32-1={5,2})  paramOff={6,6}  -> {7}" -f `
        $i, $nameHash, $blkSize, [BitConverter]::ToUInt16($b,$o+28), $f30, $texIdx, $paramOff, $tn)
}
