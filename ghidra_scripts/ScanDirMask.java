// Every instruction anywhere in the image that tests a d-pad direction mask.
// The CSS input word carries each direction twice - once in bits 4..7 and once
// in bits 16..19 - so a direction test is always an immediate of the form
// (b | b << 12) with b in {0x10,0x20,0x40,0x80}, or a union of those.
// args: <outfile>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class ScanDirMask extends GhidraScript {
    public void run() throws Exception {
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(getScriptArgs()[0])));
        Set<Long> want = new HashSet<>();
        for (int m = 1; m < 16; m++) {          // every non-empty subset of the four
            long b = 0;
            if ((m & 1) != 0) b |= 0x10;
            if ((m & 2) != 0) b |= 0x20;
            if ((m & 4) != 0) b |= 0x40;
            if ((m & 8) != 0) b |= 0x80;
            want.add(b | (b << 12));
        }
        Listing lst = currentProgram.getListing();
        InstructionIterator it = lst.getInstructions(true);
        int n = 0;
        while (it.hasNext()) {
            Instruction ins = it.next();
            boolean hit = false;
            for (int op = 0; op < ins.getNumOperands() && !hit; op++)
                for (Object o : ins.getOpObjects(op))
                    if (o instanceof Scalar && want.contains(((Scalar) o).getUnsignedValue()))
                        hit = true;
            if (!hit) continue;
            Function f = getFunctionContaining(ins.getAddress());
            out.printf("%s  %-34s %s%n", ins.getAddress(), ins.toString(),
                       f == null ? "?" : f.getName());
            n++;
        }
        out.close();
        println("wrote " + getScriptArgs()[0] + " (" + n + " hits)");
    }
}
