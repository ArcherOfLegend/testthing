// Every SHR/SAR/ROL-style shift by a given immediate, with its function.
// args: <outfile> <decimal shift> [nameSubstringFilter]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;

public class ScanShift extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));
        long want = Long.decode(a[1]);
        String filter = a.length > 2 ? a[2].toLowerCase() : null;
        int hits = 0;
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            String m = ins.getMnemonicString().toUpperCase();
            if (!(m.equals("SHR") || m.equals("SAR") || m.equals("SHL"))) continue;
            boolean match = false;
            for (int op = 0; op < ins.getNumOperands(); op++)
                for (Object o : ins.getOpObjects(op))
                    if (o instanceof Scalar && ((Scalar) o).getUnsignedValue() == want) match = true;
            if (!match) continue;
            Function f = getFunctionContaining(ins.getAddress());
            String fn = f == null ? "?" : f.getName();
            if (filter != null && !fn.toLowerCase().contains(filter)) continue;
            out.println(ins.getAddress() + "  " + fn + "  |  " + ins);
            hits++;
        }
        out.close();
        println("wrote " + a[0] + " (" + hits + " hits)");
    }
}
