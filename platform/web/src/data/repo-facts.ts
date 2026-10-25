// Build-time facts computed from the repository by platform/web/scripts/build_facts.py.
// This file is generated in CI on every push; the committed copy is a fallback
// so local builds work without running the script.

const generated = {
  generatedAt: "2026-10-10T11:20:03+02:00",
  head: "f8f3d08",
  startDate: "2026-09-06",
  totalCommits: 91,
  weeklyCommits: [
    { week: "08/31", commits: 7 },
    { week: "09/07", commits: 27 },
    { week: "09/14", commits: 16 },
    { week: "09/21", commits: 11 },
    { week: "09/28", commits: 17 },
    { week: "10/05", commits: 13 },
  ],
  testsWorld: 118,
  testsGateway: 24,
  facts: {
    typeRegistryNames: 4818,
    messageTypesDecoded: 144,
    clientFunctionsMapped: 50,
  },
} as const;

export interface RepoFacts {
  generatedAt: string;
  head: string;
  startDate: string;
  totalCommits: number;
  weeklyCommits: { week: string; commits: number }[];
  testsWorld: number;
  testsGateway: number;
  facts: { typeRegistryNames: number; messageTypesDecoded: number; clientFunctionsMapped: number };
}

export const repoFacts: RepoFacts = { ...generated };
