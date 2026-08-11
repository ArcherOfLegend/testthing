// args: <outfile>
// Every scalar immediate that could encode the CSS grid dimensions, across
// every function belonging to the character-select classes.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class ScanConstants extends GhidraScript {
    // 7 rows, 8 cols, 28 per side, 56 slots, and the /7 reciprocal.
    static final Set<Long> WANT = new HashSet<>(Arrays.asList(
        7L, 0x1cL, 0x38L, 0x24924925L, 0x92492493L, 6L, 0x1bL, 0x37L));

    public void run() throws Exception {
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(getScriptArgs()[0])));
        Listing lst = currentProgram.getListing();
        FunctionIterator fi = currentProgram.getFunctionManager().getFunctions(true);
        while (fi.hasNext()) {
            Function f = fi.next();
            String n = f.getName();
            if (!(n.contains("ChrSel") || n.contains("ChrSelect") || n.contains("CharSel")))
                continue;
            if (n.contains("__dti") || n.contains("MyDTI") || n.contains("FilePath")) continue;

            StringBuilder sb = new StringBuilder();
            InstructionIterator ii = lst.getInstructions(f.getBody(), true);
            while (ii.hasNext()) {
                Instruction ins = ii.next();
                for (int op = 0; op < ins.getNumOperands(); op++) {
                    for (Object o : ins.getOpObjects(op)) {
                        if (!(o instanceof Scalar)) continue;
                        long v = ((Scalar) o).getUnsignedValue();
                        if (!WANT.contains(v)) continue;
                        sb.append("    ").append(ins.getAddress()).append("  ")
                          .append(ins.toString()).append("\n");
                    }
                }
            }
            if (sb.length() > 0) {
                out.println("=== " + n + " @ " + f.getEntryPoint());
                out.print(sb);
            }
        }
        out.close();
        println("wrote " + getScriptArgs()[0]);
    }
}
