// args: <outfile> <addr:count> ...
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import java.io.*;

public class Disasm extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));
        Listing lst = currentProgram.getListing();
        for (int i = 1; i < a.length; i++) {
            String[] p = a[i].split(":");
            Address at = currentProgram.getAddressFactory().getAddress(p[0]);
            int n = Integer.parseInt(p[1]);
            Function f = getFunctionContaining(at);
            out.println("--- " + p[0] + "  (" + (f == null ? "?" : f.getName()) + ")");
            Instruction ins = lst.getInstructionAt(at);
            if (ins == null) ins = lst.getInstructionAfter(at);
            for (int k = 0; k < n && ins != null; k++) {
                StringBuilder hex = new StringBuilder();
                for (byte b : ins.getBytes()) hex.append(String.format("%02X ", b));
                out.printf("  %s  %-28s %s%n", ins.getAddress(), hex.toString(), ins.toString());
                ins = ins.getNext();
            }
        }
        out.close();
        println("wrote " + a[0]);
    }
}
