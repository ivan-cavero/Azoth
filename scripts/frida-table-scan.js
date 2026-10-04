
const m = Process.findModuleByName('NewWorld.exe');
const base = m.base;
const off = (va) => base.add(va - 0x140000000);
function findPointers(targetVa, label) {
  const target = off(targetVa);
  const ranges = Process.enumerateRanges('rw-').concat(Process.enumerateRanges('r--'));
  let found = [];
  const pat = target.toMatchPattern();
  for (const r of ranges) {
    if (r.size > 0x4000000) continue; // skip huge regions for speed
    try {
      Memory.scan(r.base, r.size, pat, {
        onMatch(addr, size) {
          found.push({addr: addr.toString(), range: r.base.toString()});
        },
        onComplete() {}
      });
    } catch (e) {}
  }
  return found;
}
send({ev:'scan-start'});
const a = findPointers(0x141763b70, 'b70');
send({ev:'b70-hits', n: a.length, sample: a.slice(0,10)});
const b = findPointers(0x141761dd0, 'cluster');
send({ev:'cluster-hits', n: b.length, sample: b.slice(0,10)});
