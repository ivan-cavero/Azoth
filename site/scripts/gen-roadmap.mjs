// Generate the public display copy from its canonical TypeScript source.
import { roadmapGroups } from "../src/data/roadmap-full.ts";
import { writeFileSync } from "fs";
const payload = { updatedAt: new Date().toISOString(), groups: roadmapGroups };
writeFileSync(new URL("../public/roadmap.json", import.meta.url), JSON.stringify(payload, null, 2) + "\n");
console.log("groups:", roadmapGroups.length, "items:", roadmapGroups.reduce((a, g) => a + g.items.length, 0));
