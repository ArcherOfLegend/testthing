// Every indirect CALL through a vtable slot with one of the given displacements.
// args: <outfile> <disp> [disp...]     (displacements in hex, e.g. 88 90 98 a0)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class ScanVCall extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));
        Set<Long> want = new HashSet<>();
        for (int i = 1; i < a.length; i++) want.add(Long.parseLong(a[i], 16));

        Listing lst = currentProgram.getListing();
        InstructionIterator it = lst.getInstructions(true);
        int n = 0;
        while (it.hasNext()) {
            Instruction ins = it.next();
            if (!ins.getMnemonicString().equalsIgnoreCase("CALL")) continue;
            String t = ins.toString();
            if (!t.contains("[")) continue;            // must be memory-indirect
            boolean hit = false;
            for (int op = 0; op < ins.getNumOperands() && !hit; op++)
                for (Object o : ins.getOpObjects(op))
                    if (o instanceof Scalar && want.contains(((Scalar) o).getUnsignedValue()))
                        hit = true;
            if (!hit) continue;
            Function f = getFunctionContaining(ins.getAddress());
            out.printf("%s  %-34s %s%n", ins.getAddress(), t, f == null ? "?" : f.getName());
            n++;
        }
        out.close();
        println("wrote " + a[0] + " (" + n + " hits)");
    }
}
