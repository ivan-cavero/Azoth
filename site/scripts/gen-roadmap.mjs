// Generate the public display copy from roadmap v2 (ADR 0002).
// v1 inventory is archived under src/data/archive/ — never import it here.
import { roadmapGroups } from "../src/data/roadmap-v2.ts";
import { writeFileSync } from "fs";

const payload = { updatedAt: new Date().toISOString(), groups: roadmapGroups };
writeFileSync(
  new URL("../public/roadmap.json", import.meta.url),
  JSON.stringify(payload, null, 2) + "\n",
);
console.log(
  "roadmap v2 — groups:",
  roadmapGroups.length,
  "items:",
  roadmapGroups.reduce((a, g) => a + g.items.length, 0),
);
