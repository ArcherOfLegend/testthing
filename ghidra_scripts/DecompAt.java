// args: <outfile> <addr> [addr...]
// For each address: report the containing function, its xrefs, and decompiled C.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class DecompAt extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));

        DecompInterface di = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        di.setOptions(opts);
        di.openProgram(currentProgram);

        java.util.Set<String> done = new java.util.HashSet<>();
        for (int i = 1; i < a.length; i++) {
            Address addr = currentProgram.getAddressFactory().getAddress(a[i]);
            Function f = getFunctionContaining(addr);
            out.println("//======================================================");
            if (f == null) {
                out.println("// " + a[i] + " : NO FUNCTION");
                // still show references to this address
                dumpRefs(out, addr);
                continue;
            }
            out.println("// query " + a[i] + "  ->  " + f.getName() +
                        " @ " + f.getEntryPoint() + "  (offset +0x" +
                        Long.toHexString(addr.subtract(f.getEntryPoint())) + ")");
            dumpRefs(out, f.getEntryPoint());
            if (!done.add(f.getEntryPoint().toString())) {
                out.println("// (body already printed above)");
                continue;
            }
            DecompileResults r = di.decompileFunction(f, 120, monitor);
            if (r.decompileCompleted() && r.getDecompiledFunction() != null)
                out.println(r.getDecompiledFunction().getC());
            else
                out.println("// DECOMPILE FAILED: " + r.getErrorMessage());
        }
        out.close();
        di.dispose();
        println("wrote " + a[0]);
    }

    void dumpRefs(PrintWriter out, Address target) {
        ReferenceIterator ri = currentProgram.getReferenceManager().getReferencesTo(target);
        int n = 0;
        while (ri.hasNext() && n < 25) {
            Reference r = ri.next();
            Function cf = getFunctionContaining(r.getFromAddress());
            out.println("//   xref " + r.getFromAddress() + " (" +
                        (cf == null ? "?" : cf.getName()) + ") " + r.getReferenceType());
            n++;
        }
        if (n == 0) out.println("//   (no xrefs)");
    }
}
