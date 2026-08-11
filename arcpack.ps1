<#
.SYNOPSIS
Pack a directory into an MT Framework .arc.

.EXAMPLE
.\arcpack.ps1 -Dir .\extract -Out .\mnchscmn.arc

.EXAMPLE
# -Template reproduces the original entry ordering (byte-identical rebuilds)
.\arcpack.ps1 -Dir .\extract -Out .\mnchscmn.arc -Template "<game>\nativePCx64\ui\mnchscmn.arc"

.NOTES
File names inside the archive come from the path relative to -Dir, minus the
extension: extract\ui\chs\chs_meku\chs_meku.mod -> "ui\chs\chs_meku\chs_meku".
The extension maps back to the resource-type hash, so this round-trips whatever
arc.ps1 wrote (including unknown types, which it names by their hex hash).

Files whose extension is neither a known type nor an 8-hex-digit hash are
skipped - that is what keeps generated junk such as _dds_cache\*.dds out.
#>
param(
    [Parameter(Mandatory=$true)][string]$Dir,
    [Parameter(Mandatory=$true)][string]$Out,
    [string]$Template = $null,
    [int]$Align = 32768,
    [switch]$Quiet
)

# Must stay in sync with the table in arc.ps1, or extract/pack won't round-trip.
$extToHash = @{
    'tex' = [Convert]::ToUInt32('241F5DEB',16)
    'mod' = [Convert]::ToUInt32('58A15856',16)
    'mrl' = [Convert]::ToUInt32('2749C8A8',16)
    'lmt' = [Convert]::ToUInt32('76820D81',16)
    'gui' = [Convert]::ToUInt32('22948394',16)
}

function Get-Adler32([byte[]]$data) {
    [uint32]$a = 1; [uint32]$b = 0
    foreach ($x in $data) {
        $a = ($a + $x) % 65521
        $b = ($b + $a) % 65521
    }
    return ($b -shl 16) -bor $a
}

function Compress-Zlib([byte[]]$data) {
    $ms = New-Object System.IO.MemoryStream
    $ds = New-Object System.IO.Compression.DeflateStream($ms, [System.IO.Compression.CompressionLevel]::Optimal, $true)
    $ds.Write($data, 0, $data.Length)
    $ds.Dispose()
    $deflated = $ms.ToArray(); $ms.Dispose()

    $out = New-Object System.Collections.Generic.List[byte]
    $out.Add(0x78); $out.Add(0x9C)                    # zlib header, default window
    $out.AddRange($deflated)
    $ad = Get-Adler32 $data
    $out.Add([byte](($ad -shr 24) -band 0xFF))        # adler32, big-endian
    $out.Add([byte](($ad -shr 16) -band 0xFF))
    $out.Add([byte](($ad -shr 8)  -band 0xFF))
    $out.Add([byte]( $ad          -band 0xFF))
    return $out.ToArray()
}

if (-not (Test-Path -LiteralPath $Dir -PathType Container)) { throw "Not a directory: $Dir" }
$root = (Resolve-Path -LiteralPath $Dir).Path.TrimEnd('\','/')

# ---- collect entries -------------------------------------------------------
$entries = @()
$skipped = @()
Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object {
    $ext = $_.Extension.TrimStart('.')
    $hash = $null
    if ($extToHash.ContainsKey($ext.ToLower())) {
        $hash = $extToHash[$ext.ToLower()]
    } elseif ($ext -match '^[0-9A-Fa-f]{8}$') {
        $hash = [Convert]::ToUInt32($ext,16)
    } else {
        $skipped += $_.FullName.Substring($root.Length).TrimStart('\','/')
        return
    }

    $rel  = $_.FullName.Substring($root.Length).TrimStart('\','/')
    $name = [System.IO.Path]::ChangeExtension($rel, $null).TrimEnd('.') -replace '/', '\'
    if ([System.Text.Encoding]::ASCII.GetByteCount($name) -gt 63) {
        throw "Entry name too long for the 64-byte field (>63 chars): $name"
    }

    $entries += [PSCustomObject]@{
        Name = $name; Hash = $hash; Path = $_.FullName; Key = "$name|$hash"
    }
}

if ($entries.Count -eq 0) { throw "No packable files found under $Dir" }
if ($entries.Count -gt 65535) { throw "$($entries.Count) files exceeds the u16 entry count" }

$dupes = $entries | Group-Object Key | Where-Object { $_.Count -gt 1 }
if ($dupes) { throw "Duplicate entries: $(($dupes | ForEach-Object { $_.Name }) -join ', ')" }

# ---- ordering --------------------------------------------------------------
# The game indexes by name, but keeping the shipped order makes rebuilds
# byte-comparable against the original, which is the strongest sanity check.
$version = 7
if ($Template) {
    if (-not (Test-Path -LiteralPath $Template)) { throw "Template not found: $Template" }
    $t = [System.IO.File]::ReadAllBytes($Template)
    if ([System.Text.Encoding]::ASCII.GetString($t,0,3) -ne 'ARC') { throw "Template is not an ARC" }
    $version = [BitConverter]::ToUInt16($t,4)
    $tCount  = [BitConverter]::ToUInt16($t,6)

    $byKey = @{}
    foreach ($e in $entries) { $byKey[$e.Key] = $e }
    $ordered = @(); $seen = @{}
    for ($i = 0; $i -lt $tCount; $i++) {
        $o = 8 + $i*80
        $nb = $t[$o..($o+63)]
        $nul = [Array]::IndexOf($nb,[byte]0); if ($nul -lt 0) { $nul = 64 }
        $nm = [System.Text.Encoding]::ASCII.GetString($nb,0,$nul)
        $h  = [BitConverter]::ToUInt32($t,$o+64)
        $k  = "$nm|$h"
        if ($byKey.ContainsKey($k)) { $ordered += $byKey[$k]; $seen[$k] = $true }
        elseif (-not $Quiet) { Write-Output "  template entry missing from -Dir: $nm" }
    }
    foreach ($e in $entries) { if (-not $seen.ContainsKey($e.Key)) { $ordered += $e } }
    $entries = $ordered
} else {
    $entries = $entries | Sort-Object Name
}

# ---- compress --------------------------------------------------------------
$blobs = @()
$rawSizes = @()
foreach ($e in $entries) {
    $plain = [System.IO.File]::ReadAllBytes($e.Path)
    $blobs += ,(Compress-Zlib $plain)
    $rawSizes += [uint32]$plain.Length
}

# ---- lay out ---------------------------------------------------------------
# Data always begins at the next multiple of $Align past the entry table;
# every shipped archive follows that rule (32768 / 65536 / 98304).
$hdrEnd = 8 + $entries.Count * 80
$dataStart = [int][Math]::Ceiling($hdrEnd / [double]$Align) * $Align
$total = $dataStart
foreach ($b in $blobs) { $total += $b.Length }

$outBytes = New-Object byte[] $total
[Array]::Copy([System.Text.Encoding]::ASCII.GetBytes('ARC'), 0, $outBytes, 0, 3)
$outBytes[3] = 0
[Array]::Copy([BitConverter]::GetBytes([uint16]$version),        0, $outBytes, 4, 2)
[Array]::Copy([BitConverter]::GetBytes([uint16]$entries.Count),  0, $outBytes, 6, 2)

$FLAGS = [uint32]2 -shl 29     # every shipped entry uses flag value 2
$cursor = $dataStart
for ($i = 0; $i -lt $entries.Count; $i++) {
    $o = 8 + $i*80
    $nameBytes = [System.Text.Encoding]::ASCII.GetBytes($entries[$i].Name)
    [Array]::Copy($nameBytes, 0, $outBytes, $o, $nameBytes.Length)   # rest stays NUL
    [Array]::Copy([BitConverter]::GetBytes([uint32]$entries[$i].Hash), 0, $outBytes, $o+64, 4)
    [Array]::Copy([BitConverter]::GetBytes([uint32]$blobs[$i].Length), 0, $outBytes, $o+68, 4)
    [Array]::Copy([BitConverter]::GetBytes([uint32]($rawSizes[$i] -bor $FLAGS)), 0, $outBytes, $o+72, 4)
    [Array]::Copy([BitConverter]::GetBytes([uint32]$cursor), 0, $outBytes, $o+76, 4)
    [Array]::Copy($blobs[$i], 0, $outBytes, $cursor, $blobs[$i].Length)
    $cursor += $blobs[$i].Length
}

$outDir = Split-Path $Out -Parent
if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
[System.IO.File]::WriteAllBytes($Out, $outBytes)

if (-not $Quiet) {
    if ($skipped.Count -gt 0) {
        Write-Output "skipped $($skipped.Count) non-resource file(s), e.g.: $(($skipped | Select-Object -First 3) -join ', ')"
    }
    Write-Output ("packed {0} files, dataStart={1}, {2} bytes -> {3}" -f $entries.Count, $dataStart, $total, $Out)
}
