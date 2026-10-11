// Single source of truth for build-time landing data (stats, timeline, stack,
// docs, versions, help). All user-facing strings exist in EN + ES.
// NOTE: the live roadmap comes from public/roadmap.json (English content — see
// site/README.md); this file feeds the gantt and the build-time sections.

import type { Locale } from "./i18n";
import { repoFacts } from "./repo-facts";

// First commit date comes from the repo (computed at build time in CI).
export const START_DATE = repoFacts.startDate;

export type TaskStatus = "done" | "active" | "planned";

export interface GanttTask {
  id: string;
  code: string;
  label: Record<Locale, string>;
  start: string;
  end: string;
  open?: boolean;
  progress: number;
  status: TaskStatus;
}

export interface StackEntry {
  name: string;
  role: Record<Locale, string>;
  state: "now" | "transition" | "future";
  detail: Record<Locale, string>;
}

export interface DocEntry {
  name: string;
  path: string;
  what: Record<Locale, string>;
  verified: "verified" | "partial" | "open";
}

export interface Version {
  tag: string;
  date: string;
  title: Record<Locale, string>;
  bullets: Record<Locale, string[]>;
}

export interface HelpOption {
  title: Record<Locale, string>;
  body: Record<Locale, string>;
  tag: Record<Locale, string>;
}

// ---------------------------------------------------------------- stats

export const stats = {
  commits: repoFacts.totalCommits,
  weeksActive: repoFacts.weeklyCommits.length,
  testsWorld: repoFacts.testsWorld,
  testsGateway: repoFacts.testsGateway,
  messageTypesDecoded: repoFacts.facts.messageTypesDecoded,
  clientFunctionsMapped: repoFacts.facts.clientFunctionsMapped,
  decompiledFunctions: 423542,
  typeRegistryNames: repoFacts.facts.typeRegistryNames,
  subworlds: 44,
  aoiTraits: 82,
  sessionRecord: "2 h 06 min",
  sessionRecordBefore: "27 s",
};

export const weeklyCommits = repoFacts.weeklyCommits;

// ------------------------------------------------------------- timeline

export const ganttTasks: GanttTask[] = [
  { id: "bootstrap", code: "G0.1", start: "2026-09-06", end: "2026-09-12", progress: 1, status: "done",
    label: { es: "Bootstrap, toolchain y az.py", en: "Bootstrap, toolchain and az.py" } },
  { id: "capture", code: "G0.2", start: "2026-09-11", end: "2026-09-20", progress: 1, status: "done",
    label: { es: "Capturas de sesión oficial y Game.log", en: "Official session captures and Game.log" } },
  { id: "gateway", code: "G0.3", start: "2026-09-13", end: "2026-09-24", progress: 1, status: "done",
    label: { es: "Gateway HTTP (login, hub, certificados)", en: "HTTP gateway (login, hub, certificates)" } },
  { id: "world", code: "G0.4", start: "2026-09-14", end: "2026-10-01", progress: 1, status: "done",
    label: { es: "Servidor de mundo DTLS 50 Hz", en: "DTLS world server 50 Hz" } },
  { id: "client", code: "G0.5", start: "2026-09-27", end: "2026-10-06", progress: 1, status: "done",
    label: { es: "Cliente privado + gates 1-8b", en: "Private client + gates 1-8b" } },
  { id: "protocol", code: "G0.6", start: "2026-10-01", end: "2026-10-09", progress: 1, status: "done",
    label: { es: "Protocolo: varint, bundle, 144 mensajes", en: "Protocol: varint, bundle, 144 messages" } },
  { id: "stability", code: "G0.7", start: "2026-10-04", end: "2026-10-10", progress: 1, status: "done",
    label: { es: "Sesión estable (27 s → 2 h 06 min)", en: "Stable session (27 s → 2 h 06 min)" } },
  { id: "landing", code: "N1", start: "2026-10-10", end: "2026-10-10", progress: 1, status: "done",
    label: { es: "Landing con estado en vivo", en: "Landing with live status" } },
  { id: "replication", code: "A5", start: "2026-10-10", end: "2026-10-24", open: true, progress: 0.35, status: "active",
    label: { es: "Códecs de payload por tipo de componente", en: "Fragment payload codecs per component type" } },
  { id: "physics", code: "B3", start: "2026-10-14", end: "2026-10-28", open: true, progress: 0.15, status: "active",
    label: { es: "Replicación de PhysicsTrait (cuerpo del jugador)", en: "PhysicsTrait replication (player body)" } },
  { id: "movement", code: "B4", start: "2026-10-24", end: "2026-11-08", progress: 0, status: "planned",
    label: { es: "Movimiento del jugador (WASD)", en: "Player movement (WASD)" } },
  { id: "charselect", code: "C3", start: "2026-11-01", end: "2026-11-22", progress: 0, status: "planned",
    label: { es: "Selección y creación de personaje", en: "Character select and creation" } },
  { id: "webaccount", code: "C5", start: "2026-11-10", end: "2026-11-30", progress: 0, status: "planned",
    label: { es: "Vinculación web ↔ juego", en: "Web ↔ game account link" } },
  { id: "db", code: "C1", start: "2026-11-01", end: "2026-12-06", progress: 0, status: "planned",
    label: { es: "Base de datos propia y persistencia", en: "Owned database and persistence" } },
  { id: "regions", code: "E2", start: "2026-11-15", end: "2027-01-15", progress: 0, status: "planned",
    label: { es: "14 territorios jugables", en: "14 playable territories" } },
  { id: "settlements", code: "E3", start: "2026-12-01", end: "2027-01-31", progress: 0, status: "planned",
    label: { es: "Asentamientos, NPCs y estaciones", en: "Settlements, NPCs and stations" } },
  { id: "spawns", code: "F2", start: "2026-12-15", end: "2027-02-15", progress: 0, status: "planned",
    label: { es: "Spawns de NPCs, IA y navegación", en: "NPC spawns, AI and navigation" } },
  { id: "missions", code: "G2", start: "2027-01-05", end: "2027-02-28", progress: 0, status: "planned",
    label: { es: "Misiones y progresión", en: "Missions and progression" } },
  { id: "economy", code: "H5", start: "2027-01-15", end: "2027-03-15", progress: 0, status: "planned",
    label: { es: "Trading Post, inventario y economía", en: "Trading Post, inventory and economy" } },
  { id: "social", code: "I1", start: "2027-02-01", end: "2027-03-31", progress: 0, status: "planned",
    label: { es: "Chat, grupos y hermandades", en: "Chat, groups and companies" } },
  { id: "pvp", code: "J5", start: "2027-03-01", end: "2027-05-15", progress: 0, status: "planned",
    label: { es: "Guerra 50v50 y asedios", en: "50v50 war and sieges" } },
  { id: "pvp-modes", code: "K15", start: "2027-03-15", end: "2027-06-01", progress: 0, status: "planned",
    label: { es: "Outpost Rush, arena 3v3, BR y CTF", en: "Outpost Rush, 3v3 arena, BR and CTF" } },
  { id: "dungeons", code: "K1", start: "2027-04-01", end: "2027-06-30", progress: 0, status: "planned",
    label: { es: "Instancing y 12 expediciones", en: "Instancing and 12 expeditions" } },
  { id: "housing", code: "L1", start: "2027-05-01", end: "2027-06-15", progress: 0, status: "planned",
    label: { es: "Viviendas y decoración", en: "Housing and decoration" } },
  { id: "events", code: "M2", start: "2027-05-15", end: "2027-07-01", progress: 0, status: "planned",
    label: { es: "Eventos estacionales activables", en: "Toggleable seasonal events" } },
  { id: "rust-gateway", code: "O1", start: "2027-01-10", end: "2027-03-15", progress: 0, status: "planned",
    label: { es: "Rust: gateway completo", en: "Rust: full gateway" } },
  { id: "rust-world", code: "O2", start: "2027-03-01", end: "2027-06-30", progress: 0, status: "planned",
    label: { es: "Rust: runtime de mundo (paridad total)", en: "Rust: world runtime (full parity)" } },
  { id: "capacity", code: "O4", start: "2027-06-01", end: "2027-09-30", progress: 0, status: "planned",
    label: { es: "Capacidad: 2.500 → 10.000 jugadores", en: "Capacity: 2,500 → 10,000 players" } },
];

// ---------------------------------------------------------------- stack

export const stack: StackEntry[] = [
  {
    name: "Python 3 (stdlib)", state: "now",
    role: { es: "Gateway HTTP + servidor de mundo (prototipo)", en: "HTTP gateway + world server (prototype)" },
    detail: {
      es: "Sin dependencias externas salvo pyOpenSSL para DTLS. Es el laboratorio donde se entiende y verifica el protocolo.",
      en: "No external dependencies except pyOpenSSL for DTLS. It is the lab where the protocol is understood and verified.",
    },
  },
  {
    name: "Rust — gateway", state: "transition",
    role: { es: "Reescritura del gateway HTTP", en: "Rewrite of the HTTP gateway" },
    detail: {
      es: "Primera pieza del puerto: el gateway completo (login, hub, descubrimiento, certificados) pasa a Rust con paridad medida en el borde de red antes de retirar el prototipo.",
      en: "First port piece: the full gateway (login, hub, discovery, certificates) moves to Rust with measured wire-boundary parity before retiring the prototype.",
    },
  },
  {
    name: "Rust — world runtime", state: "future",
    role: { es: "Reescritura del servidor de mundo", en: "Rewrite of the world server" },
    detail: {
      es: "DTLS, tick autoritativo y replicación records/fragments. Solo se porta comportamiento ya verificado en Python; paridad total antes de retirar el prototipo.",
      en: "DTLS, authoritative tick and record/fragment replication. Only verified behavior is ported; full parity before retiring the prototype.",
    },
  },
  {
    name: "Astro + Tailwind", state: "now",
    role: { es: "Esta landing y la web pública", en: "This landing and the public web" },
    detail: {
      es: "Estático, sin runtime en el servidor. Roadmap y estado en vivo vía JSON.",
      en: "Static, no server runtime. Roadmap and live status via JSON.",
    },
  },
  {
    name: "Caddy", state: "now",
    role: { es: "Enrutado local, certificados y CA privada", en: "Local routing, certificates and private CA" },
    detail: {
      es: "Sirve las APIs previas al mundo y gestiona la confianza del cliente.",
      en: "Serves the pre-world APIs and manages client trust.",
    },
  },
  {
    name: "Ghidra + Capstone", state: "now",
    role: { es: "Ingeniería inversa del cliente", en: "Client reverse engineering" },
    detail: {
      es: "423.542 funciones decompiladas en el corpus masivo; 50 objetivos priorizados en el manifiesto de campaña.",
      en: "423,542 functions decompiled in the bulk corpus; 50 prioritized targets in the campaign manifest.",
    },
  },
  {
    name: "PowerShell", state: "now",
    role: { es: "Launcher y operación en Windows", en: "Windows launcher and operations" },
    detail: {
      es: "az.ps1 descubre la librería de Steam y orquesta az.py.",
      en: "az.ps1 discovers the Steam library and orchestrates az.py.",
    },
  },
];

// ----------------------------------------------------------------- docs

export const docs: DocEntry[] = [
  { name: "JAVELIN-PROTOCOL.md", path: "research/docs/JAVELIN-PROTOCOL.md", verified: "verified",
    what: { es: "Referencia consolidada del protocolo de red", en: "Consolidated network protocol reference" } },
  { name: "javelin-messages.json", path: "research/atlas/javelin-messages.json", verified: "verified",
    what: { es: "144 tipos de mensaje con GUID y wire type", en: "144 message types with GUID and wire type" } },
  { name: "SERVER-CONTRACT.md", path: "research/docs/SERVER-CONTRACT.md", verified: "verified",
    what: { es: "Lo que el cliente espera del servidor, fase a fase", en: "What the client expects from the server, phase by phase" } },
  { name: "PRIVATE-CLIENT-RUNBOOK.md", path: "research/docs/PRIVATE-CLIENT-RUNBOOK.md", verified: "verified",
    what: { es: "Cómo levantar y parchear una partida privada (gates 1-8b)", en: "How to bring up and patch a private session (gates 1-8b)" } },
  { name: "client-functions.json", path: "research/atlas/client-functions.json", verified: "verified",
    what: { es: "Nombres de funciones nativas confirmadas con evidencia", en: "Confirmed native function names with evidence" } },
  { name: "az-type-registry.json", path: "research/atlas/az-type-registry.json", verified: "verified",
    what: { es: "4.818 nombres de tipos del cliente, 750 en la tabla de tipos", en: "4,818 client type names, 750 in the type table" } },
  { name: "aoi-trait-registry.json", path: "research/atlas/aoi-trait-registry.json", verified: "verified",
    what: { es: "82 traits AOI, 2.276 pares trait/mensaje", en: "82 AOI traits, 2,276 trait/message pairs" } },
  { name: "Fragment payload codecs", path: "services/world/src/azoth_world/javelin/", verified: "open",
    what: { es: "Codificación del payload de cada tipo de componente", en: "Payload encoding for each component type" } },
  { name: "Player physics components", path: "STATUS.md", verified: "open",
    what: { es: "«El jugador no tiene componente de física» está SIN PROBAR (GUIDs desplazados)", en: "'Player has no physics component' is UNPROVEN (shifted GUIDs)" } },
  { name: "State stream idempotency", path: "HANDOFF.md", verified: "open",
    what: { es: "Re-aplicar un record capturado en vivo: pregunta abierta", en: "Re-applying a live-captured record: open question" } },
];

// ------------------------------------------------------------- versions

export const versions: Version[] = [
  { tag: "v0.1", date: "2026-09-06",
    title: { es: "Arranque del proyecto", en: "Project kickoff" },
    bullets: {
      es: ["Repositorio, entry point az.py / az.ps1", "Toolchain checksum-verified en rutas locales ignoradas"],
      en: ["Repository, az.py / az.ps1 entry point", "Checksum-verified toolchain in ignored local paths"],
    } },
  { tag: "v0.2", date: "2026-09-13",
    title: { es: "Gateway HTTP", en: "HTTP gateway" },
    bullets: {
      es: ["APIs previas al mundo servidas al cliente", "Capturas de sesión oficial como fuente de verdad"],
      en: ["Pre-world APIs served to the client", "Official session captures as source of truth"],
    } },
  { tag: "v0.3", date: "2026-09-24",
    title: { es: "Servidor de mundo DTLS", en: "DTLS world server" },
    bullets: {
      es: ["Javelin/REP sobre DTLS con pyOpenSSL", "Replay de Carrier chunks desde capturas reales"],
      en: ["Javelin/REP over DTLS with pyOpenSSL", "Carrier chunk replay from real captures"],
    } },
  { tag: "v0.4", date: "2026-10-06",
    title: { es: "Cliente privado estable hasta spawn", en: "Private client stable through spawn" },
    bullets: {
      es: ["Gates 1-8b documentados en el runbook", "Mundo renderizado con jugador poseído y HUD completo"],
      en: ["Gates 1-8b documented in the runbook", "World rendered with possessed player and full HUD"],
    } },
  { tag: "v0.5", date: "2026-10-09",
    title: { es: "Protocolo decodificado", en: "Protocol decoded" },
    bullets: {
      es: ["Varint, contenedor 0x08 y registro de 144 mensajes con tests", "Bundle verificado como secuencia de records con fragments"],
      en: ["Varint, 0x08 container and 144-message registry with tests", "Bundle verified as record sequence with fragments"],
    } },
  { tag: "v0.6", date: "2026-10-10",
    title: { es: "Sesión estable 2 h 06 min", en: "Stable session 2 h 06 min" },
    bullets: {
      es: ["Heartbeat e input-response fuera del camino del replay", "Campos 16-bit con wrap; tick con reloj propio (Pearson 0,995 → 0,180)"],
      en: ["Heartbeat and input-response off the replay path", "16-bit field wrap; self-clocking tick (Pearson 0.995 → 0.180)"],
    } },
];

// ----------------------------------------------------------------- help

export const helpOptions: HelpOption[] = [
  {
    title: { es: "Ingeniería inversa", en: "Reverse engineering" },
    tag: { es: "Crítico", en: "Critical" },
    body: {
      es: "Derivar códecs de fragmentos con Ghidra y probes en vivo. Es la vía crítica: cada tipo de componente decodificado acerca el movimiento.",
      en: "Derive fragment codecs with Ghidra and live probes. This is the critical path: every decoded component type brings movement closer.",
    },
  },
  {
    title: { es: "Rust", en: "Rust" },
    tag: { es: "Puerto", en: "Port" },
    body: {
      es: "El puerto empieza por el gateway completo y sigue con el runtime de mundo, comparando en el borde de red contra el prototipo Python con los mismos fixtures.",
      en: "The port starts with the full gateway and follows with the world runtime, comparing at the wire boundary against the Python prototype with the same fixtures.",
    },
  },
  {
    title: { es: "Infra y medición", en: "Infra & measurement" },
    tag: { es: "Escala", en: "Scale" },
    body: {
      es: "Bancos de carga, telemetría de tick y ancho de banda. La claim de capacidad solo cuenta con run representativo medido.",
      en: "Load harnesses, tick and bandwidth telemetry. Capacity claims only count with measured representative runs.",
    },
  },
  {
    title: { es: "Documentación", en: "Documentation" },
    tag: { es: "Siempre", en: "Always" },
    body: {
      es: "Mantener el atlas de evidencia: toda conclusión con su VA, qué se observó y cómo se confirmó. Sin chat como fuente.",
      en: "Keep the evidence atlas: every conclusion with its address, what was observed and how it was confirmed. Chat is not a source.",
    },
  },
];

// ----------------------------------------------------------------- live

export const liveDefaults = {
  agentRunning: false,
  lastHeartbeat: null as string | null,
  services: {
    gateway: false,
    world: false,
    caddy: false,
  },
};
