// Ghidra headless helper: decompile specific function ranges and dump the C.
//
// Invoked by research/tools/re/decomp.py. Args are "<startHex>[-<endHex>]" pairs.
// Output goes to $DECOMP_OUT (append mode), one "########## <range> ##########"
// header per target followed by the decompiled C.
//
// Compiled by decomp.py with javac against the Ghidra jars; Ghidra 12 loads
// scripts as OSGi bundles, so a .class must live in a script dir (a bare .java
// outside a bundle fails with "class could not be found").

import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import java.io.FileWriter;
import java.io.PrintWriter;

public class DecompileTargets extends GhidraScript {
    @Override
    public void run() throws Exception {
        String outPath = System.getenv("DECOMP_OUT");
        if (outPath == null) {
            outPath = "decomp.txt";
        }
        try (PrintWriter out = new PrintWriter(new FileWriter(outPath, true))) {
            DecompInterface ifc = new DecompInterface();
            ifc.setOptions(ifc.getOptions());
            ifc.openProgram(currentProgram);
            for (String arg : getScriptArgs()) {
                String[] parts = arg.split("-");
                long start = Long.parseUnsignedLong(parts[0], 16);
                long end = parts.length > 1 ? Long.parseUnsignedLong(parts[1], 16) : start;
                Address s = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(start);
                Address e = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(end);
                out.println("########## " + arg + " ##########");
                try {
                    // Walk the range so createFunction has instructions to own.
                    Address cur = s;
                    while (cur.compareTo(e) <= 0) {
                        if (!disassemble(cur)) {
                            break;
                        }
                        Instruction insn = getInstructionAt(cur);
                        if (insn == null) {
                            break;
                        }
                        cur = insn.getMaxAddress().add(1);
                    }
                    Function f = createFunction(s, null);
                    if (f == null) {
                        f = getFunctionContaining(s);
                    }
                    if (f == null) {
                        out.println("NO FUNCTION at " + arg);
                    } else {
                        out.println("FUNC " + f.getName() + " entry=" + f.getEntryPoint()
                                + " body=" + f.getBody().getNumAddresses());
                        DecompileResults res = ifc.decompileFunction(f, 300, monitor);
                        if (res != null && res.decompileCompleted()) {
                            out.println(res.getDecompiledFunction().getC());
                        } else {
                            out.println("DECOMP-FAIL "
                                    + (res == null ? "null" : res.getErrorMessage()));
                        }
                    }
                } catch (Exception ex) {
                    out.println("ERR " + ex);
                }
                out.flush();
            }
        }
        println("decompiled -> " + outPath);
    }
}
