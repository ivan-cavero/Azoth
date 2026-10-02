// Turn off the decompiler-based analyzers before the bulk auto-analysis of a
// 179 MB executable with 423,579 functions.
//
// Why: the layer-1 corpus was imported with -noanalysis, so it has no strings,
// no symbols and no data references — you cannot ask "what references this
// address", which is exactly the question needed to find a function reached
// through a vtable. A full analysis fixes that, but the default analyzer set
// spends nearly all of its time in the decompiler (parameter ID, switch
// analysis, stack). Those add nothing for navigation by strings, references and
// data xrefs, so they are disabled and the remaining analyzers do the work.
//
// The log records which analyzers were found and their final state, so a run
// can be checked afterwards instead of assumed.

import ghidra.app.script.GhidraScript;
import ghidra.framework.options.Options;

public class DisableSlowAnalyzers extends GhidraScript {
    private static final String[] SLOW = {
        "Decompiler Parameter ID",
        "Decompiler Switch Analysis",
        "Aggressive Instruction Finder",
        "Stack",
        "Variadic Function Signature Override",
        "Non-Returning Functions - Discovered",
        "Create Address Tables",
        "Golang String Analyzer",
    };

    @Override
    public void run() throws Exception {
        Options opts = currentProgram.getOptions("Analyzers");
        java.util.Set<String> present = new java.util.HashSet<String>();
        for (String key : opts.getOptionNames()) {
            present.add(key);
        }
        for (String name : SLOW) {
            if (!present.contains(name)) {
                println("ANALYZE not-present: " + name);
                continue;
            }
            try {
                opts.setBoolean(name, false);
                println("ANALYZE disabled: " + name);
            } catch (Exception ex) {
                println("ANALYZE failed to disable " + name + ": " + ex);
            }
        }
        for (String key : opts.getOptionNames()) {
            try {
                println("ANALYZE state " + key + "=" + opts.getBoolean(key, true));
            } catch (Exception ignored) {
                // Non-boolean analyzer options (e.g. string or int) are fine.
            }
        }
    }
}
