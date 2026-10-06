// Headless bulk decompile of every .pdata function in the cached NewWorld project.
//
// One JVM, read-only project: disassembly and function records stay in memory
// and are discarded on exit, so the ~480MB project database is not rewritten.
// Workers each own a DecompInterface. The program is only mutated on the
// script thread, between decompile chunks.
//
// Env (set by corpus.py):
//   DECOMP_CORPUS_DIR      output directory
//   DECOMP_CORPUS_RANGES   "start end" hex lines, end exclusive
//   DECOMP_CORPUS_THREADS  decompiler workers
//   DECOMP_CORPUS_LIMIT    stop after this many attempts (0 = all)
//   DECOMP_CORPUS_TIMEOUT  seconds per function
//   DECOMP_CORPUS_CHUNK    functions disassembled per round

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.symbol.SourceType;
import ghidra.util.task.TaskMonitor;
import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;

public class DecompileCorpus extends GhidraScript {
    private static final int SHARD_FUNCTIONS = 250;

    private Path outDir;
    private Path shardDir;
    private int threads;
    private int limit;
    private int timeoutSecs;
    private int chunkSize;
    private final Set<Long> already = new HashSet<Long>();
    private final List<DecompInterface> opened = Collections.synchronizedList(new ArrayList<DecompInterface>());
    private final ThreadLocal<DecompInterface> localIfc = new ThreadLocal<DecompInterface>() {
        @Override
        protected DecompInterface initialValue() {
            return openIfc();
        }
    };

    private final Object progressLock = new Object();
    private final Object writeLock = new Object();
    private final List<Result> buffer = new ArrayList<Result>();
    private int nextShard = 1;
    private int alreadyCount;
    private final AtomicInteger attempted = new AtomicInteger();
    private final AtomicInteger okCount = new AtomicInteger();
    private final AtomicInteger failCount = new AtomicInteger();
    private int total;
    private String phase = "starting";
    private String error = "";
    private long startedAt;
    private long decompileStartedAt;
    private volatile boolean stop;

    @Override
    public void run() throws Exception {
        startedAt = System.currentTimeMillis();
        outDir = Paths.get(env("DECOMP_CORPUS_DIR"));
        shardDir = outDir.resolve("shards");
        Files.createDirectories(shardDir);
        threads = intEnv("DECOMP_CORPUS_THREADS", 8);
        limit = intEnv("DECOMP_CORPUS_LIMIT", 0);
        timeoutSecs = intEnv("DECOMP_CORPUS_TIMEOUT", 60);
        chunkSize = intEnv("DECOMP_CORPUS_CHUNK", 1024);
        loadDone();
        alreadyCount = already.size();
        List<long[]> ranges = loadRanges(Paths.get(env("DECOMP_CORPUS_RANGES")));
        total = ranges.size();
        writeProgress();
        Thread heart = new Thread(this::heartbeat, "corpus-heartbeat");
        heart.setDaemon(true);
        heart.start();
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        try {
            decompileAll(ranges, pool);
            flushBuffer();
            phase = "complete";
            error = "";
            writeProgress();
            println("CORPUS complete attempted=" + attempted.get()
                    + " ok=" + okCount.get() + " fail=" + failCount.get());
        } catch (Exception ex) {
            stop = true;
            phase = "failed";
            error = ex.toString();
            try {
                flushBuffer();
            } catch (Exception ignored) {
                // The original failure is the one to surface.
            }
            writeProgress();
            throw ex;
        } finally {
            stop = true;
            pool.shutdownNow();
            for (DecompInterface ifc : opened) {
                try {
                    ifc.dispose();
                } catch (Exception ignored) {
                    // Disposal is best-effort on the way out.
                }
            }
        }
    }

    private void decompileAll(List<long[]> ranges, ExecutorService pool) throws Exception {
        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager funcs = currentProgram.getFunctionManager();
        int accepted = 0;
        for (int base = 0; base < ranges.size() && !monitor.isCancelled() && !stop; base += chunkSize) {
            if (limit > 0 && accepted >= limit) {
                break;
            }
            int end = Math.min(ranges.size(), base + chunkSize);
            AddressSet starts = new AddressSet();
            AddressSet restrict = new AddressSet();
            List<long[]> todo = new ArrayList<long[]>();
            for (int i = base; i < end; i++) {
                if (limit > 0 && accepted + todo.size() >= limit) {
                    break;
                }
                long[] range = ranges.get(i);
                if (already.contains(range[0]) || range[1] <= range[0]) {
                    continue;
                }
                Address entry = space.getAddress(range[0]);
                Address last = space.getAddress(range[1] - 1);
                if (entry == null || last == null) {
                    record(range[0], range[1], "badaddr", "", "address not in space");
                    continue;
                }
                starts.add(entry);
                restrict.add(entry, last);
                todo.add(range);
            }
            if (todo.isEmpty()) {
                continue;
            }
            phase = "disassemble";
            writeProgress();
            DisassembleCommand cmd = new DisassembleCommand(starts, restrict, true);
            // Analyzers per chunk would dominate the run and try to mutate far
            // past the function body. The decompiler only needs instructions.
            cmd.enableCodeAnalysis(false);
            cmd.applyTo(currentProgram, monitor);
            List<Work> batch = defineFunctions(funcs, space, todo);
            if (batch.isEmpty()) {
                continue;
            }
            if (decompileStartedAt == 0) {
                decompileStartedAt = System.currentTimeMillis();
            }
            phase = "decompile";
            writeProgress();
            accepted += batch.size();
            runBatch(pool, batch);
            println("CORPUS chunk done accepted=" + accepted
                    + " attempted=" + attempted.get()
                    + " ok=" + okCount.get()
                    + " fail=" + failCount.get());
        }
        if (monitor.isCancelled()) {
            throw new InterruptedException("monitor cancelled");
        }
    }

    private List<Work> defineFunctions(FunctionManager funcs, AddressSpace space, List<long[]> todo)
            throws Exception {
        // The imported program has 1-byte function bodies at many pdata entries.
        // Leaving those in place makes the decompiler clip to a single byte, so
        // each entry is rebuilt to the pdata range before decompile.
        List<Work> batch = new ArrayList<Work>();
        int tx = currentProgram.startTransaction("corpus-chunk");
        try {
            for (long[] range : todo) {
                Address entry = space.getAddress(range[0]);
                Address last = space.getAddress(range[1] - 1);
                AddressSet body = new AddressSet(entry, last);
                List<Address> occupying = new ArrayList<Address>();
                for (Function other : funcs.getFunctions(body, true)) {
                    occupying.add(other.getEntryPoint());
                }
                for (Address occupied : occupying) {
                    funcs.removeFunction(occupied);
                }
                try {
                    Function created = funcs.createFunction(null, entry, body, SourceType.DEFAULT);
                    if (created == null) {
                        record(range[0], range[1], "nofunc", "", "createFunction returned null");
                    } else {
                        if (created.getBody().getNumAddresses() != range[1] - range[0]) {
                            created.setBody(body);
                        }
                        batch.add(new Work(created, range[0], range[1]));
                    }
                } catch (Exception ex) {
                    record(range[0], range[1], "nofunc", "", ex.toString());
                }
            }
        } finally {
            currentProgram.endTransaction(tx, true);
        }
        return batch;
    }

    private void runBatch(ExecutorService pool, List<Work> batch) throws Exception {
        int workers = Math.min(threads, batch.size());
        int share = (batch.size() + workers - 1) / workers;
        List<Future<?>> futures = new ArrayList<Future<?>>();
        for (int t = 0; t < workers; t++) {
            int from = t * share;
            int to = Math.min(batch.size(), from + share);
            if (from >= to) {
                continue;
            }
            final int start = from;
            final int stopAt = to;
            futures.add(pool.submit(new Runnable() {
                @Override
                public void run() {
                    DecompInterface ifc = localIfc.get();
                    for (int i = start; i < stopAt && !stop; i++) {
                        Work work = batch.get(i);
                        Result result;
                        try {
                            result = decompileOne(ifc, work);
                        } catch (Exception ex) {
                            replaceIfc();
                            ifc = localIfc.get();
                            result = Result.fail(work, ex.toString());
                        }
                        addResult(result);
                    }
                }
            }));
        }
        for (Future<?> future : futures) {
            future.get();
        }
    }

    private Result decompileOne(DecompInterface ifc, Work work) {
        String name = work.fn.getName();
        DecompileResults res = ifc.decompileFunction(work.fn, timeoutSecs, TaskMonitor.DUMMY);
        if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) {
            return new Result(work.start, work.end, "ok", name, res.getDecompiledFunction().getC());
        }
        String message = res == null ? "null" : res.getErrorMessage();
        return new Result(work.start, work.end, "fail", name,
                message == null ? "decompile failed" : message);
    }

    private void replaceIfc() {
        DecompInterface dead = localIfc.get();
        try {
            dead.dispose();
        } catch (Exception ignored) {
            // The replacement below is what the worker needs.
        }
        opened.remove(dead);
        localIfc.set(openIfc());
    }

    private DecompInterface openIfc() {
        DecompInterface ifc = new DecompInterface();
        ifc.setOptions(ifc.getOptions());
        ifc.openProgram(currentProgram);
        opened.add(ifc);
        return ifc;
    }

    private void addResult(Result result) {
        attempted.incrementAndGet();
        if ("ok".equals(result.status)) {
            okCount.incrementAndGet();
        } else {
            failCount.incrementAndGet();
        }
        synchronized (writeLock) {
            buffer.add(result);
            if (buffer.size() >= SHARD_FUNCTIONS) {
                try {
                    flushBufferLocked();
                } catch (IOException ex) {
                    throw new RuntimeException(ex);
                }
            }
        }
    }

    private void record(long start, long end, String status, String name, String message) {
        addResult(new Result(start, end, status, name, message));
    }

    private void flushBuffer() throws IOException {
        synchronized (writeLock) {
            flushBufferLocked();
        }
    }

    private void flushBufferLocked() throws IOException {
        if (buffer.isEmpty()) {
            return;
        }
        buffer.sort((a, b) -> Long.compare(a.start, b.start));
        String name = String.format(Locale.ROOT, "shard-%06d", nextShard);
        Path cTmp = shardDir.resolve(name + ".c.tmp");
        Path cFinal = shardDir.resolve(name + ".c");
        Path idxTmp = shardDir.resolve(name + ".idx.tmp");
        Path idxFinal = shardDir.resolve(name + ".idx");
        try (BufferedWriter c = Files.newBufferedWriter(cTmp, StandardCharsets.UTF_8);
                BufferedWriter idx = Files.newBufferedWriter(idxTmp, StandardCharsets.UTF_8)) {
            for (Result result : buffer) {
                c.write("########## ");
                c.write(Long.toHexString(result.start));
                c.write("-");
                c.write(Long.toHexString(result.end));
                c.write(" status=");
                c.write(result.status);
                c.write(" name=");
                c.write(result.name == null || result.name.isEmpty() ? "-" : result.name);
                c.write(" ##########\n");
                if ("ok".equals(result.status)) {
                    c.write("FUNC ");
                    c.write(result.name);
                    c.write(" entry=");
                    c.write(Long.toHexString(result.start));
                    c.write(" body=");
                    c.write(Long.toString(result.end - result.start));
                    c.write("\n");
                    c.write(result.text == null ? "" : result.text);
                    if (result.text != null && !result.text.endsWith("\n")) {
                        c.write("\n");
                    }
                } else {
                    c.write(result.status.toUpperCase(Locale.ROOT));
                    c.write(" ");
                    c.write(result.text == null ? "" : result.text.replace('\n', ' '));
                    c.write("\n");
                }
                idx.write(Long.toHexString(result.start));
                idx.write("\t");
                idx.write(result.status);
                idx.write("\t");
                idx.write(Integer.toString(result.text == null ? 0 : result.text.length()));
                idx.write("\t");
                idx.write(name);
                idx.write(".c\n");
            }
        }
        // Index is published only after the C shard is in place, so a crash
        // cannot mark functions done when their text was still a temp file.
        Files.move(cTmp, cFinal, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        Files.move(idxTmp, idxFinal, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        nextShard++;
        buffer.clear();
        writeProgress();
    }

    private void loadDone() throws IOException {
        if (!Files.isDirectory(shardDir)) {
            return;
        }
        try (DirectoryStream<Path> stream = Files.newDirectoryStream(shardDir, "shard-*.idx")) {
            for (Path idx : stream) {
                String fileName = idx.getFileName().toString();
                int n = Integer.parseInt(fileName.substring("shard-".length(), fileName.length() - 4));
                if (n >= nextShard) {
                    nextShard = n + 1;
                }
                try (BufferedReader reader = Files.newBufferedReader(idx, StandardCharsets.UTF_8)) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        int tab = line.indexOf('\t');
                        if (tab <= 0) {
                            continue;
                        }
                        already.add(Long.parseUnsignedLong(line.substring(0, tab), 16));
                    }
                }
            }
        }
        try (DirectoryStream<Path> temps = Files.newDirectoryStream(shardDir, "*.tmp")) {
            for (Path tmp : temps) {
                Files.deleteIfExists(tmp);
            }
        }
    }

    private static List<long[]> loadRanges(Path file) throws IOException {
        List<long[]> ranges = new ArrayList<long[]>();
        try (BufferedReader reader = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) {
                    continue;
                }
                String[] parts = line.split("\\s+");
                long start = Long.parseUnsignedLong(parts[0], 16);
                long end = Long.parseUnsignedLong(parts[1], 16);
                ranges.add(new long[] {start, end});
            }
        }
        return ranges;
    }

    private void heartbeat() {
        while (!stop) {
            try {
                Thread.sleep(10000);
                writeProgress();
            } catch (InterruptedException ex) {
                return;
            }
        }
    }

    private void writeProgress() {
        synchronized (progressLock) {
            long now = System.currentTimeMillis();
            int attemptedNow = attempted.get();
            int finished = alreadyCount + attemptedNow;
            double rate = 0;
            long eta = -1;
            if (decompileStartedAt > 0 && attemptedNow > 0) {
                double seconds = Math.max(0.001, (now - decompileStartedAt) / 1000.0);
                rate = attemptedNow / seconds;
                int remaining = Math.max(0, total - finished);
                if (limit > 0) {
                    remaining = Math.max(0, Math.min(remaining, limit - attemptedNow));
                }
                eta = (long) (remaining / rate);
            }
            String json = "{\n"
                    + "  \"status\": \"" + jsonEscape(phase) + "\",\n"
                    + "  \"phase\": \"" + jsonEscape(phase) + "\",\n"
                    + "  \"total\": " + total + ",\n"
                    + "  \"already\": " + alreadyCount + ",\n"
                    + "  \"attempted\": " + attemptedNow + ",\n"
                    + "  \"finished\": " + finished + ",\n"
                    + "  \"ok\": " + okCount.get() + ",\n"
                    + "  \"fail\": " + failCount.get() + ",\n"
                    + "  \"shards\": " + (nextShard - 1) + ",\n"
                    + "  \"threads\": " + threads + ",\n"
                    + "  \"timeout_s\": " + timeoutSecs + ",\n"
                    + "  \"rate_per_s\": " + String.format(Locale.ROOT, "%.3f", rate) + ",\n"
                    + "  \"eta_s\": " + eta + ",\n"
                    + "  \"started\": \"" + Instant.ofEpochMilli(startedAt) + "\",\n"
                    + "  \"updated\": \"" + Instant.now() + "\",\n"
                    + "  \"error\": \"" + jsonEscape(error) + "\"\n"
                    + "}\n";
            try {
                Path dest = outDir.resolve("progress.json");
                Path tmp = outDir.resolve("progress.json.tmp");
                Files.writeString(tmp, json, StandardCharsets.UTF_8);
                try {
                    Files.move(tmp, dest, java.nio.file.StandardCopyOption.REPLACE_EXISTING,
                            java.nio.file.StandardCopyOption.ATOMIC_MOVE);
                } catch (java.nio.file.AtomicMoveNotSupportedException ex) {
                    Files.move(tmp, dest, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                }
            } catch (IOException ex) {
                println("CORPUS progress write failed: " + ex);
            }
        }
    }

    private static String jsonEscape(String raw) {
        if (raw == null) {
            return "";
        }
        return raw.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ").replace("\r", " ");
    }

    private static String env(String key) {
        String value = System.getenv(key);
        if (value == null || value.isEmpty()) {
            throw new IllegalStateException(key + " unset");
        }
        return value;
    }

    private static int intEnv(String key, int fallback) {
        String value = System.getenv(key);
        if (value == null || value.isEmpty()) {
            return fallback;
        }
        return Integer.parseInt(value);
    }

    private static final class Result {
        final long start;
        final long end;
        final String status;
        final String name;
        final String text;

        Result(long start, long end, String status, String name, String text) {
            this.start = start;
            this.end = end;
            this.status = status;
            this.name = name == null ? "" : name;
            this.text = text == null ? "" : text;
        }

        static Result fail(Work work, String message) {
            return new Result(work.start, work.end, "fail", work.fn.getName(), message);
        }
    }

    private static final class Work {
        final Function fn;
        final long start;
        final long end;

        Work(Function fn, long start, long end) {
            this.fn = fn;
            this.start = start;
            this.end = end;
        }
    }
}
