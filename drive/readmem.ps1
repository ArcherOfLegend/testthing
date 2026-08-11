# Read int32s out of the running game. Usage: readmem.ps1 -Address 0x138360000 -Count 64
param([string]$Address, [int]$Count = 64, [int]$Width = 8)

if (-not ("Win32Mem" -as [type])) {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Mem {
  [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint a, bool inh, int pid);
  [DllImport("kernel32.dll")] public static extern bool ReadProcessMemory(
      IntPtr h, IntPtr addr, byte[] buf, int size, out IntPtr read);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  public static byte[] Read(int pid, long addr, int len) {
    IntPtr h = OpenProcess(0x0010, false, pid);   // PROCESS_VM_READ
    if (h == IntPtr.Zero) throw new Exception("OpenProcess failed: " + Marshal.GetLastWin32Error());
    byte[] b = new byte[len]; IntPtr got;
    bool ok = ReadProcessMemory(h, new IntPtr(addr), b, len, out got);
    CloseHandle(h);
    if (!ok) throw new Exception("ReadProcessMemory failed at 0x" + addr.ToString("X"));
    return b;
  }
}
"@
}

$p = Get-Process umvc3 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) { Write-Error "umvc3 not running"; exit 1 }
$addr = [Convert]::ToInt64($Address.Replace("0x", ""), 16)
$bytes = [Win32Mem]::Read($p.Id, $addr, $Count * 4)

for ($r = 0; $r -lt [math]::Ceiling($Count / $Width); $r++) {
  $line = "0x{0:X}  " -f ($addr + $r * $Width * 4)
  for ($c = 0; $c -lt $Width; $c++) {
    $i = $r * $Width + $c
    if ($i -ge $Count) { break }
    $line += "{0,5}" -f [BitConverter]::ToInt32($bytes, $i * 4)
  }
  $line
}
