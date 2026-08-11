// Every instruction whose immediate equals one of the given values, with the
// function that contains it. args: <outfile> <hexvalue> [hexvalue...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class FindConst extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));
        Set<Long> want = new HashSet<>();
        for (int i = 1; i < a.length; i++)
            want.add(Long.decode(a[i]) & 0xFFFFFFFFL);

        int hits = 0;
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            for (int op = 0; op < ins.getNumOperands(); op++) {
                for (Object o : ins.getOpObjects(op)) {
                    if (!(o instanceof Scalar)) continue;
                    long v = ((Scalar) o).getUnsignedValue() & 0xFFFFFFFFL;
                    if (!want.contains(v)) continue;
                    Function f = getFunctionContaining(ins.getAddress());
                    out.println(ins.getAddress() + "  " + String.format("%08x", v) + "  " +
                                (f == null ? "?" : f.getName()) + "  |  " + ins);
                    hits++;
                }
            }
        }
        // and data words holding the value
        DataIterator di = currentProgram.getListing().getDefinedData(true);
        while (di.hasNext()) {
            Data d = di.next();
            Object v = d.getValue();
            if (v instanceof Scalar && want.contains(((Scalar) v).getUnsignedValue() & 0xFFFFFFFFL)) {
                out.println("DATA " + d.getAddress() + "  " + d);
                hits++;
            }
        }
        out.close();
        println("wrote " + a[0] + " (" + hits + " hits)");
    }
}
