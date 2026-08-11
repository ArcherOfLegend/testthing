# Write int32s into the running game, for probes that would otherwise need a
# plugin rebuild and relaunch. Usage:
#   writemem.ps1 -Address 0x138360000 -Index 5 -Values 1,30
# writes Values into consecutive int32 slots starting at Address + Index*4.
param([string]$Address, [int]$Index = 0, [int[]]$Values)

if (-not ("Win32MemW" -as [type])) {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32MemW {
  [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr OpenProcess(uint a, bool inh, int pid);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool WriteProcessMemory(
      IntPtr h, IntPtr addr, byte[] buf, int size, out IntPtr wrote);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool ReadProcessMemory(
      IntPtr h, IntPtr addr, byte[] buf, int size, out IntPtr read);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  // PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
  public static byte[] Read(int pid, long addr, int len) {
    IntPtr h = OpenProcess(0x0038, false, pid);
    if (h == IntPtr.Zero) throw new Exception("OpenProcess failed: " + Marshal.GetLastWin32Error());
    byte[] b = new byte[len]; IntPtr got;
    bool ok = ReadProcessMemory(h, new IntPtr(addr), b, len, out got);
    CloseHandle(h);
    if (!ok) throw new Exception("ReadProcessMemory failed");
    return b;
  }
  public static void Write(int pid, long addr, byte[] b) {
    IntPtr h = OpenProcess(0x0038, false, pid);
    if (h == IntPtr.Zero) throw new Exception("OpenProcess failed: " + Marshal.GetLastWin32Error());
    IntPtr wrote;
    bool ok = WriteProcessMemory(h, new IntPtr(addr), b, b.Length, out wrote);
    CloseHandle(h);
    if (!ok) throw new Exception("WriteProcessMemory failed at 0x" + addr.ToString("X"));
  }
}
"@
}

$p = Get-Process umvc3 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) { Write-Error "umvc3 not running"; exit 1 }
$base = [Convert]::ToInt64($Address.Replace("0x", ""), 16)
$at = $base + $Index * 4

$before = [Win32MemW]::Read($p.Id, $at, $Values.Count * 4)
$buf = New-Object byte[] ($Values.Count * 4)
for ($i = 0; $i -lt $Values.Count; $i++) {
  [BitConverter]::GetBytes([int]$Values[$i]).CopyTo($buf, $i * 4)
}
[Win32MemW]::Write($p.Id, $at, $buf)
$after = [Win32MemW]::Read($p.Id, $at, $Values.Count * 4)

for ($i = 0; $i -lt $Values.Count; $i++) {
  "slot {0,3}  {1,5} -> {2,5}" -f ($Index + $i),
    [BitConverter]::ToInt32($before, $i * 4), [BitConverter]::ToInt32($after, $i * 4)
}
