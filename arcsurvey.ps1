# Survey .arc headers: what is the data-start rule, which flag values occur,
# are entries stored in offset order, is there padding between blobs?
param([Parameter(Mandatory=$true)][string]$Root)

$allFlags = @{}
$allVers  = @{}
$rows = @()

Get-ChildItem $Root -Recurse -Filter *.arc | ForEach-Object {
    $b = [System.IO.File]::ReadAllBytes($_.FullName)
    if ($b.Length -lt 8 -or [System.Text.Encoding]::ASCII.GetString($b,0,3) -ne 'ARC') { return }
    $ver   = [BitConverter]::ToUInt16($b,4)
    $count = [BitConverter]::ToUInt16($b,6)
    $hdr   = 8 + $count*80
    $minOff = [uint32]::MaxValue
    $ordered = $true; $prevOff = 0; $gaps = 0
    $ends = @()
    for ($i=0; $i -lt $count; $i++) {
        $o = 8 + $i*80
        $comp = [BitConverter]::ToUInt32($b,$o+68)
        $raw  = [BitConverter]::ToUInt32($b,$o+72)
        $off  = [BitConverter]::ToUInt32($b,$o+76)
        $fl   = $raw -shr 29
        $allFlags[$fl] = $true
        if ($off -lt $minOff) { $minOff = $off }
        if ($off -lt $prevOff) { $ordered = $false }
        $prevOff = $off
        $ends += ,@($off, $comp)
    }
    # count gaps between consecutive blobs (in offset order)
    $sorted = $ends | Sort-Object { $_[0] }
    for ($i=1; $i -lt $sorted.Count; $i++) {
        if ($sorted[$i][0] -ne ($sorted[$i-1][0] + $sorted[$i-1][1])) { $gaps++ }
    }
    $allVers[$ver] = $true
    $rows += [PSCustomObject]@{
        Name=$_.Name; Ver=$ver; Count=$count; HdrEnd=$hdr; DataStart=$minOff
        Pow2 = if ($minOff -gt 0) { [Math]::Round([Math]::Log($minOff,2),3) } else { 0 }
        Ordered=$ordered; Gaps=$gaps; Size=$b.Length
    }
}

$rows | Sort-Object Count -Descending | Select-Object -First 25 |
    Format-Table Name,Ver,Count,HdrEnd,DataStart,Pow2,Ordered,Gaps,Size -AutoSize | Out-String -Width 200 -Stream

Write-Output ""
Write-Output ("archives            : {0}" -f $rows.Count)
Write-Output ("versions seen       : {0}" -f (($allVers.Keys | Sort-Object) -join ', '))
Write-Output ("flag values seen    : {0}" -f (($allFlags.Keys | Sort-Object) -join ', '))
Write-Output ("distinct DataStart  : {0}" -f (($rows.DataStart | Sort-Object -Unique) -join ', '))
Write-Output ("any unordered       : {0}" -f (($rows | Where-Object {-not $_.Ordered}).Count))
Write-Output ("any with gaps       : {0}" -f (($rows | Where-Object {$_.Gaps -gt 0}).Count))
Write-Output ("max HdrEnd          : {0}" -f (($rows.HdrEnd | Measure-Object -Maximum).Maximum))
Write-Output ("HdrEnd > DataStart  : {0}" -f (($rows | Where-Object {$_.HdrEnd -gt $_.DataStart}).Count))
