// Every instruction whose memory operand uses one of the given displacements,
// restricted to functions whose name matches a substring filter.
// args: <outfile> <nameFilter|-> <disp> [disp...]   (displacements in hex)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class ScanDisp extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));
        String filter = a[1].equals("-") ? null : a[1];
        Set<Long> want = new HashSet<>();
        for (int i = 2; i < a.length; i++) want.add(Long.parseLong(a[i], 16));

        Listing lst = currentProgram.getListing();
        InstructionIterator it = lst.getInstructions(true);
        int n = 0;
        while (it.hasNext()) {
            Instruction ins = it.next();
            String t = ins.toString();
            if (!t.contains("[")) continue;
            boolean hit = false;
            for (int op = 0; op < ins.getNumOperands() && !hit; op++)
                for (Object o : ins.getOpObjects(op))
                    if (o instanceof Scalar && want.contains(((Scalar) o).getUnsignedValue()))
                        hit = true;
            if (!hit) continue;
            Function f = getFunctionContaining(ins.getAddress());
            String fn = f == null ? "?" : f.getName();
            if (filter != null && !fn.contains(filter)) continue;
            StringBuilder hex = new StringBuilder();
            for (byte b : ins.getBytes()) hex.append(String.format("%02X ", b));
            out.printf("%s  %-26s %-38s %s%n", ins.getAddress(), hex.toString(), t, fn);
            n++;
        }
        out.close();
        println("wrote " + a[0] + " (" + n + " hits)");
    }
}
