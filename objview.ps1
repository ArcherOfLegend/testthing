param(
    [Parameter(Mandatory=$true)][string]$Obj,
    [string]$Group = $null,      # regex to select groups; null = all
    [int]$W = 108,
    [int]$H = 34
)

$verts = New-Object System.Collections.ArrayList
$cur = ''
$sel = New-Object System.Collections.ArrayList   # vertices belonging to selected groups
$all = New-Object System.Collections.ArrayList

foreach ($line in [System.IO.File]::ReadLines($Obj)) {
    if ($line.StartsWith('g ')) { $cur = $line.Substring(2); continue }
    if ($line.StartsWith('v ')) {
        $p = $line.Split(' ')
        $x = [double]$p[1]; $y = [double]$p[2]; $z = [double]$p[3]
        [void]$all.Add(@($x,$y,$z))
        if (-not $Group -or $cur -match $Group) { [void]$sel.Add(@($x,$y,$z,$cur)) }
    }
}

Write-Output "total verts: $($all.Count)   selected: $($sel.Count)   group filter: $(if($Group){$Group}else{'<all>'})"
if ($sel.Count -eq 0) { return }

$minX = ($sel | ForEach-Object { $_[0] } | Measure-Object -Minimum).Minimum
$maxX = ($sel | ForEach-Object { $_[0] } | Measure-Object -Maximum).Maximum
$minY = ($sel | ForEach-Object { $_[1] } | Measure-Object -Minimum).Minimum
$maxY = ($sel | ForEach-Object { $_[1] } | Measure-Object -Maximum).Maximum
$minZ = ($sel | ForEach-Object { $_[2] } | Measure-Object -Minimum).Minimum
$maxZ = ($sel | ForEach-Object { $_[2] } | Measure-Object -Maximum).Maximum
Write-Output ("X [{0:F1} .. {1:F1}]  Y [{2:F1} .. {3:F1}]  Z [{4:F1} .. {5:F1}]" -f $minX,$maxX,$minY,$maxY,$minZ,$maxZ)

$grid = New-Object 'int[,]' $H,$W
foreach ($v in $sel) {
    $fx = if ($maxX -gt $minX) { ($v[0]-$minX)/($maxX-$minX) } else { 0 }
    $fy = if ($maxY -gt $minY) { ($v[1]-$minY)/($maxY-$minY) } else { 0 }
    $cx = [Math]::Min($W-1, [int]($fx*($W-1)))
    $cy = [Math]::Min($H-1, [int]((1-$fy)*($H-1)))
    $grid[$cy,$cx] = $grid[$cy,$cx] + 1
}

$ramp = ' .:-=+*#%@'
$sb = New-Object System.Text.StringBuilder
for ($r=0; $r -lt $H; $r++) {
    $line = New-Object System.Text.StringBuilder
    for ($c=0; $c -lt $W; $c++) {
        $n = $grid[$r,$c]
        if ($n -eq 0) { [void]$line.Append(' ') }
        else {
            $i = [Math]::Min($ramp.Length-1, [int]([Math]::Log($n+1,2)))
            [void]$line.Append($ramp[$i])
        }
    }
    [void]$sb.AppendLine($line.ToString().TrimEnd())
}
Write-Output $sb.ToString()
