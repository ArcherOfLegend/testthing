// args: <outfile> <tableAddr> <count>  - table of char* , print index -> string
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import java.io.*;

public class DumpPtrStrings extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));
        Address base = currentProgram.getAddressFactory().getAddress(a[1]);
        int n = Integer.parseInt(a[2]);
        Memory mem = currentProgram.getMemory();
        for (int i = 0; i < n; i++) {
            long ptr = mem.getLong(base.add((long) i * 8));
            String s = "<null>";
            if (ptr != 0) {
                StringBuilder sb = new StringBuilder();
                Address p = currentProgram.getAddressFactory().getAddress(Long.toHexString(ptr));
                for (int k = 0; k < 64; k++) {
                    byte b = mem.getByte(p.add(k));
                    if (b == 0) break;
                    sb.append((char) (b & 0xFF));
                }
                s = sb.toString();
            }
            out.printf("%3d  %s%n", i, s);
        }
        out.close();
        println("wrote " + a[0]);
    }
}
