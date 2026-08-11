// Dump every user-named function and data symbol from the community database.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class DumpSymbols extends GhidraScript {
    public void run() throws Exception {
        String path = getScriptArgs()[0];
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(path)));
        out.println("# program: " + currentProgram.getName());
        out.println("# imagebase: " + currentProgram.getImageBase());
        out.println("# exe: " + currentProgram.getExecutablePath());

        int nf = 0, nn = 0;
        FunctionIterator fi = currentProgram.getFunctionManager().getFunctions(true);
        while (fi.hasNext()) {
            Function f = fi.next();
            nf++;
            String n = f.getName();
            if (n.startsWith("FUN_") || n.startsWith("thunk_FUN_")) continue;
            nn++;
            out.println("FUNC " + f.getEntryPoint() + " " + n + " | " +
                        f.getSignature().getPrototypeString());
        }

        SymbolTable st = currentProgram.getSymbolTable();
        SymbolIterator si = st.getSymbolIterator();
        int nd = 0;
        while (si.hasNext()) {
            Symbol s = si.next();
            if (s.isDynamic()) continue;
            SymbolType t = s.getSymbolType();
            if (t != SymbolType.LABEL) continue;
            String n = s.getName();
            if (n.startsWith("DAT_") || n.startsWith("PTR_") || n.startsWith("LAB_") ||
                n.startsWith("SUB_") || n.startsWith("s_") || n.startsWith("u_") ||
                n.startsWith("caseD_") || n.startsWith("switchD") || n.startsWith("FUN_")) continue;
            nd++;
            out.println("DATA " + s.getAddress() + " " + n);
        }

        out.println("# functions total=" + nf + " named=" + nn + " datalabels=" + nd);
        out.close();
        println("wrote " + path + " (named funcs " + nn + "/" + nf + ", data " + nd + ")");
    }
}
