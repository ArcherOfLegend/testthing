// Any reference landing inside a byte range? A detour that overwrites a branch
// target crashes the moment something jumps into the middle of it.
// args: <outfile> <startAddr:length> ...
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.*;
import java.io.*;

public class XrefsIn extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));
        ReferenceManager rm = currentProgram.getReferenceManager();
        for (int i = 1; i < a.length; i++) {
            String[] p = a[i].split(":");
            Address start = currentProgram.getAddressFactory().getAddress(p[0]);
            int n = Integer.parseInt(p[1]);
            out.println("--- " + p[0] + " .. +" + n);
            int total = 0;
            for (int k = 0; k < n; k++) {
                Address at = start.add(k);
                ReferenceIterator it = rm.getReferencesTo(at);
                while (it.hasNext()) {
                    Reference r = it.next();
                    total++;
                    out.printf("  offset +%d  from %s  (%s)%n",
                               k, r.getFromAddress(), r.getReferenceType());
                }
            }
            out.println("  " + (total == 0 ? "clear - nothing references these bytes"
                                           : total + " reference(s) INTO the range"));
        }
        out.close();
        println("wrote " + a[0]);
    }
}
