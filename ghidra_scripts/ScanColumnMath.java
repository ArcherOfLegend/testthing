// Every instruction in a range that encodes the 8-column grid: masking a slot
// with 7, shifting it by 3, or recombining col + row*8 with an LEA scale of 8.
// args: <outfile> <startAddr> <endAddr>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import java.io.*;

public class ScanColumnMath extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[0])));
        Address start = currentProgram.getAddressFactory().getAddress(a[1]);
        Address end = currentProgram.getAddressFactory().getAddress(a[2]);
        Listing lst = currentProgram.getListing();
        InstructionIterator it = lst.getInstructions(start, true);
        int n = 0;
        while (it.hasNext()) {
            Instruction ins = it.next();
            if (ins.getAddress().compareTo(end) > 0) break;
            String m = ins.getMnemonicString().toUpperCase();
            String t = ins.toString();
            boolean hit =
                (m.equals("AND") && (t.endsWith(",0x7") || t.endsWith(",0xf"))) ||
                ((m.equals("SAR") || m.equals("SHR")) && (t.endsWith(",0x3") || t.endsWith(",0x4"))) ||
                (m.equals("LEA") && (t.contains("*0x8]") || t.contains("*0x10]"))) ||
                (m.equals("IMUL") && (t.endsWith(",0x8") || t.endsWith(",0x10"))) ||
                ((m.equals("ADD") || m.equals("SUB")) && (t.endsWith(",0x8") || t.endsWith(",0x10")));
            if (!hit) continue;
            Function f = getFunctionContaining(ins.getAddress());
            StringBuilder hex = new StringBuilder();
            for (byte b : ins.getBytes()) hex.append(String.format("%02X ", b));
            out.printf("%s  %-26s %-32s %s%n", ins.getAddress(), hex.toString(), t,
                       f == null ? "?" : f.getName());
            n++;
        }
        out.close();
        println("wrote " + a[0] + " (" + n + " hits)");
    }
}
