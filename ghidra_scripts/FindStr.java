// args: <outfile> <substring> [substring...]
// Every ASCII string in the image containing any of the substrings, with the
// functions that reference it. Resource names are the way into UI code: a model
// is loaded by name, so whoever names it is whoever positions it.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class FindStr extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));
        java.util.List<String> want = new java.util.ArrayList<>();
        for (int i = 1; i < a.length; i++) want.add(a[i].toLowerCase());

        int hits = 0;
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            if (!b.isInitialized()) continue;
            byte[] buf = new byte[(int) b.getSize()];
            b.getBytes(b.getStart(), buf);
            int start = -1;
            for (int i = 0; i <= buf.length; i++) {
                int c = i < buf.length ? (buf[i] & 0xff) : 0;
                boolean printable = c >= 0x20 && c < 0x7f;
                if (printable) { if (start < 0) start = i; continue; }
                if (start >= 0 && i - start >= 4) {
                    String s = new String(buf, start, i - start, "ISO-8859-1");
                    String low = s.toLowerCase();
                    boolean match = false;
                    for (String w : want) if (low.contains(w)) { match = true; break; }
                    if (match) {
                        Address at = b.getStart().add(start);
                        out.println("STR " + at + "  " + s);
                        hits++;
                        for (Reference r : getReferencesTo(at)) {
                            Function f = getFunctionContaining(r.getFromAddress());
                            out.println("    xref " + r.getFromAddress() + " " +
                                        (f == null ? "(no function)" : f.getName()) +
                                        " [" + r.getReferenceType() + "]");
                        }
                    }
                    start = -1;
                } else start = -1;
            }
        }
        out.println("# " + hits + " string(s)");
        out.close();
        println("wrote " + a[0] + " (" + hits + " strings)");
    }
}
