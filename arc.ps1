# MT Framework .arc extractor / lister
param(
    [Parameter(Mandatory=$true)][string]$Path,
    [string]$Out = $null,          # if set, extract to this dir
    [string]$Filter = $null        # only extract entries whose name matches this regex
)

$known = @{}
$known[[uint32]0x241F5DEB] = 'tex'
$known[[uint32]0x58A15856] = 'mod'
$known[[uint32]0x2749C8A8] = 'mrl'
$known[[uint32]0x76820D81] = 'lmt'
$known[[uint32]0x22948394] = 'gui'

$bytes = [System.IO.File]::ReadAllBytes($Path)

$magic = [System.Text.Encoding]::ASCII.GetString($bytes, 0, 3)
if ($magic -ne 'ARC') { throw "Not an ARC file: $Path" }
$version = [BitConverter]::ToUInt16($bytes, 4)
$count   = [BitConverter]::ToUInt16($bytes, 6)

Write-Output "ARC version=$version files=$count  ($Path)"

$ENTRY = 80
$results = @()
for ($i = 0; $i -lt $count; $i++) {
    $off = 8 + ($i * $ENTRY)
    $nameBytes = $bytes[$off..($off+63)]
    $nul = [Array]::IndexOf($nameBytes, [byte]0)
    if ($nul -lt 0) { $nul = 64 }
    $name = [System.Text.Encoding]::ASCII.GetString($nameBytes, 0, $nul)

    $hash     = [BitConverter]::ToUInt32($bytes, $off + 64)
    $compSize = [BitConverter]::ToUInt32($bytes, $off + 68)
    $rawSize  = [BitConverter]::ToUInt32($bytes, $off + 72)
    $dataOff  = [BitConverter]::ToUInt32($bytes, $off + 76)
    $decSize  = $rawSize -band 0x1FFFFFFF
    $flags    = $rawSize -shr 29

    $ext = if ($known.ContainsKey($hash)) { $known[$hash] } else { ('{0:X8}' -f $hash) }

    $results += [PSCustomObject]@{
        Index = $i; Name = $name; Ext = $ext; Hash = ('{0:X8}' -f $hash)
        Comp = $compSize; Dec = $decSize; Flags = $flags; Offset = $dataOff
    }
}

$results | Format-Table -AutoSize | Out-String -Width 300 | Write-Output

if ($Out) {
    if (-not (Test-Path $Out)) { New-Item -ItemType Directory -Force -Path $Out | Out-Null }
    foreach ($r in $results) {
        if ($Filter -and ($r.Name -notmatch $Filter) -and ($r.Ext -notmatch $Filter)) { continue }
        $comp = New-Object byte[] $r.Comp
        [Array]::Copy($bytes, $r.Offset, $comp, 0, $r.Comp)

        # zlib stream -> skip 2-byte header, raw deflate
        $ms  = New-Object System.IO.MemoryStream(,$comp)
        $ms.Position = 2
        $ds  = New-Object System.IO.Compression.DeflateStream($ms, [System.IO.Compression.CompressionMode]::Decompress)
        $outMs = New-Object System.IO.MemoryStream
        try { $ds.CopyTo($outMs) } catch { Write-Output "  !! inflate failed for $($r.Name)" }
        $ds.Dispose(); $ms.Dispose()
        $data = $outMs.ToArray(); $outMs.Dispose()

        $rel = ($r.Name -replace '\\', '/') + '.' + $r.Ext
        $dest = Join-Path $Out $rel
        $destDir = Split-Path $dest -Parent
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Force -Path $destDir | Out-Null }
        [System.IO.File]::WriteAllBytes($dest, $data)
        Write-Output ("extracted {0}  ({1} -> {2} bytes)" -f $rel, $r.Comp, $data.Length)
    }
}
