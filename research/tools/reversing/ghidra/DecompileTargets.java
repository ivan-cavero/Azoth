// Ghidra headless helper: decompile specific function ranges and dump the C.
//
// Invoked by research/tools/reversing/decomp.py. One-shot args are
// "<startHex>[-<endHex>]" pairs; output goes to $DECOMP_OUT (append).
//
// $DECOMP_SERVE=1 keeps this process alive and pulls jobs from $DECOMP_QUEUE
// (request.txt -> request.done). That avoids paying JVM + project open on
// every function. -readOnly on the headless command means the ~480MB project
// database is not rewritten when the process finally exits.
//
// Compiled by decomp.py with javac against the Ghidra jars; Ghidra 12 loads
// scripts as OSGi bundles, so a .class must live in a script dir.

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

public class DecompileTargets extends GhidraScript {
    @Override
    public void run() throws Exception {
        if ("1".equals(System.getenv("DECOMP_SERVE"))) {
            serve();
            return;
        }
        String outPath = System.getenv("DECOMP_OUT");
        if (outPath == null) {
            outPath = "decomp.txt";
        }
        try (PrintWriter out = new PrintWriter(new FileWriter(outPath, true))) {
            DecompInterface ifc = openIfc();
            for (String arg : getScriptArgs()) {
                decompileArg(ifc, arg, out);
            }
        }
        println("decompiled -> " + outPath);
    }

    private DecompInterface openIfc() {
        DecompInterface ifc = new DecompInterface();
        ifc.setOptions(ifc.getOptions());
        ifc.openProgram(currentProgram);
        return ifc;
    }

    private void serve() throws Exception {
        String q = System.getenv("DECOMP_QUEUE");
        if (q == null || q.isEmpty()) {
            throw new IllegalStateException("DECOMP_QUEUE unset");
        }
        File queue = new File(q);
        if (!queue.isDirectory() && !queue.mkdirs()) {
            throw new IllegalStateException("cannot create " + q);
        }
        DecompInterface ifc = openIfc();
        Files.writeString(new File(queue, "ready").toPath(), "ready\n", StandardCharsets.UTF_8);
        println("DECOMP-SERVER ready");
        File stop = new File(queue, "stop");
        File req = new File(queue, "request.txt");
        while (!monitor.isCancelled() && !stop.exists()) {
            if (req.isFile()) {
                handleRequest(ifc, req);
            } else {
                Thread.sleep(100);
            }
        }
        println("DECOMP-SERVER stop");
    }

    private void handleRequest(DecompInterface ifc, File req) throws Exception {
        File queue = req.getParentFile();
        File busy = new File(queue, "request.txt.busy");
        File done = new File(queue, "request.done");
        if (done.exists() && !done.delete()) {
            println("DECOMP-SERVER could not clear request.done");
        }
        if (!req.renameTo(busy)) {
            return;
        }
        List<String> lines = Files.readAllLines(busy.toPath(), StandardCharsets.UTF_8);
        busy.delete();
        String outPath = "decomp.txt";
        List<String> ranges = new ArrayList<String>();
        for (String line : lines) {
            String t = line.trim();
            if (t.isEmpty() || t.startsWith("#")) {
                continue;
            }
            if (t.startsWith("out=")) {
                outPath = t.substring(4).trim();
            } else {
                ranges.add(t);
            }
        }
        File outFile = new File(outPath);
        File parent = outFile.getParentFile();
        if (parent != null && !parent.isDirectory()) {
            parent.mkdirs();
        }
        String status = "ok";
        try (PrintWriter out = new PrintWriter(new FileWriter(outFile, false))) {
            if (ranges.isEmpty()) {
                out.println("ERR empty request");
                status = "ERR empty request";
            }
            for (String arg : ranges) {
                decompileArg(ifc, arg, out);
            }
        } catch (Exception ex) {
            status = "ERR " + ex;
        }
        Files.writeString(done.toPath(), status + "\n", StandardCharsets.UTF_8);
        println("DECOMP-SERVER job -> " + outPath + " " + status);
    }

    private void decompileArg(DecompInterface ifc, String arg, PrintWriter out) {
        String[] parts = arg.split("-");
        long start = Long.parseUnsignedLong(parts[0], 16);
        long end = parts.length > 1 ? Long.parseUnsignedLong(parts[1], 16) : start;
        Address s = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(start);
        Address e = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(end);
        out.println("########## " + arg + " ##########");
        try {
            // Walk the range so createFunction has instructions to own.
            // createFunction wants the real entry: a mid-instruction start
            // becomes a 1-byte halt_baddata stub (seen 2026-09-20 on 146b6e000).
            Address cur = s;
            while (cur != null && cur.compareTo(e) <= 0) {
                if (!disassemble(cur)) {
                    break;
                }
                Instruction insn = getInstructionAt(cur);
                if (insn == null) {
                    break;
                }
                cur = insn.getMaxAddress().add(1);
            }
            Function f = getFunctionAt(s);
            if (f == null) {
                f = createFunction(s, null);
            }
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
