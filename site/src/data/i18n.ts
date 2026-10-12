// UI translations. The roadmap content itself stays English (data file);
// everything else on the page is available in EN and ES.

export type Locale = "es" | "en";

export const locales: Locale[] = ["es", "en"];

export const localeNames: Record<Locale, string> = { es: "ES", en: "EN" };

export const ui = {
  es: {
    metaTitle: "Azoth — Servidor privado de New World",
    metaDescription:
      "Estado en vivo, roadmap y progreso verificable del proyecto Azoth.",
    nav: {
      estado: "Estado",
      timeline: "Timeline",
      roadmap: "Roadmap",
      stack: "Stack",
      docs: "Verificación",
      ayudar: "Ayudar",
      participar: "Participar",
    },
    hero: {
      badgeOn: "Agente en ejecución",
      badgeOff: "Agente detenido",
      title1: "Un servidor privado de New World,",
      title2: "construido a prueba visible.",
      lead: "Azoth decodifica el protocolo del cliente, levanta un gateway y un mundo DTLS propios, y documenta cada conclusión con evidencia. Aquí puedes ver qué corre ahora, qué está hecho, qué está verificado y cuánto falta — sin humo.",
      cta1: "Ver el progreso en vivo",
      cta2: "Roadmap completo",
      stats: [
        ["días desde el día 1", "commits", "tests en verde", "tipos de mensaje decodificados", "tipos de cliente mapeados"],
      ][0],
    },
    live: {
      title: "¿Qué está corriendo ahora?",
      lead: "Lectura directa del stack local: agente de desarrollo, gateway, mundo y Caddy. El panel se refresca solo cada 30 segundos.",
      agent: "Agente de desarrollo",
      agentSub: "sesión de trabajo sobre el repo",
      services: [
        { name: "Gateway HTTP", detail: "login · hub · certificados" },
        { name: "Mundo DTLS", detail: "Javelin/REP · tick 50 Hz" },
        { name: "Caddy", detail: "enrutado privado · CA local" },
      ],
      running: "corriendo",
      stopped: "parado",
      source: "fuente",
      sourceDetail: "se regenera desde la máquina que ejecuta el stack",
    },
    gantt: {
      title: "Timeline de entregables",
      lead: "Las barras abiertas llegan hasta AHORA; en el bloqueo activo no publicamos fecha de fin hasta conocer el camino técnico. Las fechas futuras son una secuencia orientativa, no compromisos.",
      closed: "entregables cerrados",
      search: "Buscar entregables",
      ranges: ["7 DÍAS", "1 MES", "TODO"],
      listHeader: "VERSIÓN · HECHAS",
      now: "AHORA",
      swipe: "DESLIZA →",
    },
    roadmap: {
      title: "Roadmap completo",
      lead: "Puntos concretos con su evidencia: un tipo de componente del cliente (4.818 registrados), un mundo del PAK del juego (44 submundos), o documentación pública del juego. Se actualiza en vivo desde roadmap.json. (El contenido del roadmap está en inglés.)",
      filters: ["TODO", "HECHO", "EN CURSO", "PLANIFICADO", "INVESTIGANDO"],
      summary: (d: number, a: number, t: number) => `${d} hechos · ${a} en curso · ${t} total`,
      sources: "fuentes",
      effortNote: "Los tamaños S/M/L/XL son estimaciones de esfuerzo, no compromisos.",
    },
    stack: {
      title: "Lenguajes y stack",
      lead: "Qué se usa hoy, para qué, y cuándo está planeado el cambio. El prototipo Python no se toca hasta que cada comportamiento tenga paridad medida en Rust.",
      now: "AHORA",
      transition: "TRANSICIÓN",
      future: "FUTURO",
      portRule: "REGLA DEL PUERTO",
      portText:
        "Python → Rust solo con paridad verificada en el borde de red, mismos fixtures y resultado de cliente observado.",
    },
    docs: {
      title: "Qué está verificado",
      lead: "Cada conclusión vive en el atlas con su evidencia: dirección, qué se observó y cómo se confirmó. Lo no verificado se marca como tal — aquí también.",
      verified: "VERIFICADO",
      open: "ABIERTO",
      counter: (v: number, t: number) => `${v}/${t} referencias verificadas`,
    },
    pace: {
      title: "Ritmo y ETA",
      lead: "El ritmo del histórico da contexto, pero no fija el ETA del bloqueo actual. No publicamos fecha de cierre hasta identificar el camino técnico.",
      commitsTitle: "Commits por semana",
      avg: (n: string) => `media ${n} / semana`,
      rows: {
        paceNow: "Ritmo actual",
        tests: "Tests automatizados",
        decompiled: "Funciones decompiladas",
        prioritized: "Funciones priorizadas",
        tick: "Tick del mundo",
        subworlds: "Submundos en assets",
        next: "Próximo hito",
      },
      tickValue: "50 Hz actual · 60 Hz objetivo",
      subworldsValue: "44 jugables en el PAK",
      testsValue: "mundo · gateway",
      nextValue: "Diagnóstico ALC + movimiento · sin ETA",
    },
    versions: {
      title: "Versiones",
      lead: "Una versión por hito que cambia lo que el sistema es capaz de hacer, desde el día 1 del proyecto.",
    },
    help: {
      title: "Cómo ayudar",
      lead: "El proyecto avanza por evidencia, no por horas. Si alguna de estas líneas te encaja, hay trabajo concreto y bien acotado esperando.",
      supportTitle: "Apoyar el proyecto",
      supportBody:
        "Cada hora de análisis y cada sesión de pruebas se paga en tiempo de máquina y ancho de banda. El progreso se publica aquí, con la misma honestidad para quien contribuye y para quien apoya.",
      supportCta: "Hablar con el equipo",
    },
    footer: {
      brand: "Azoth — servidor privado de New World",
      data: "datos: research/atlas · STATUS.md · histórico git — actualizado en cada build",
    },
  },

  en: {
    metaTitle: "Azoth — New World private server",
    metaDescription:
      "Live status, roadmap and verifiable progress of the Azoth project.",
    nav: {
      estado: "Status",
      timeline: "Timeline",
      roadmap: "Roadmap",
      stack: "Stack",
      docs: "Verification",
      ayudar: "Help",
      participar: "Join",
    },
    hero: {
      badgeOn: "Agent running",
      badgeOff: "Agent idle",
      title1: "A New World private server,",
      title2: "built on visible proof.",
      lead: "Azoth decodes the client protocol, runs its own gateway and DTLS world server, and documents every conclusion with evidence. Here you can see what is running right now, what is done, what is verified and how much is left — no smoke.",
      cta1: "See live progress",
      cta2: "Full roadmap",
      stats: ["days since day 1", "commits", "tests passing", "message types decoded", "client types mapped"],
    },
    live: {
      title: "What is running right now?",
      lead: "Direct read of the local stack: development agent, gateway, world and Caddy. The panel refreshes itself every 30 seconds.",
      agent: "Development agent",
      agentSub: "working session on the repo",
      services: [
        { name: "HTTP Gateway", detail: "login · hub · certificates" },
        { name: "DTLS World", detail: "Javelin/REP · 50 Hz tick" },
        { name: "Caddy", detail: "private routing · local CA" },
      ],
      running: "running",
      stopped: "stopped",
      source: "source",
      sourceDetail: "regenerated from the machine running the stack",
    },
    gantt: {
      title: "Deliverables timeline",
      lead: "Open bars extend to NOW. We publish no finish date for the active blocker until its technical path is known. Future dates show sequence, not commitments.",
      closed: "deliverables closed",
      search: "Search deliverables",
      ranges: ["7 DAYS", "1 MONTH", "ALL"],
      listHeader: "VERSION · DONE",
      now: "NOW",
      swipe: "SWIPE →",
    },
    roadmap: {
      title: "Full roadmap",
      lead: "Concrete items with their evidence: a client component type (4,818 registered), a world from the game PAK (44 subworlds), or public game documentation. Updates live from roadmap.json. (Roadmap content is in English.)",
      filters: ["ALL", "DONE", "ACTIVE", "PLANNED", "RESEARCH"],
      summary: (d: number, a: number, t: number) => `${d} done · ${a} active · ${t} total`,
      sources: "sources",
      effortNote: "S/M/L/XL sizes are effort estimates, not commitments.",
    },
    stack: {
      title: "Languages & stack",
      lead: "What is used today, for what, and when the change is planned. The Python prototype stays untouched until every behavior has measured parity in Rust.",
      now: "NOW",
      transition: "TRANSITION",
      future: "FUTURE",
      portRule: "PORT RULE",
      portText:
        "Python → Rust only with verified parity at the wire boundary, same fixtures and observed client results.",
    },
    docs: {
      title: "What is verified",
      lead: "Every conclusion lives in the atlas with its evidence: address, what was observed and how it was confirmed. What is not verified is marked as such — here too.",
      verified: "VERIFIED",
      open: "OPEN",
      counter: (v: number, t: number) => `${v}/${t} references verified`,
    },
    pace: {
      title: "Pace & ETA",
      lead: "Historical pace provides context; it does not set an ETA for the current blocker. We will not publish a finish date until its technical path is identified.",
      commitsTitle: "Commits per week",
      avg: (n: string) => `avg ${n} / week`,
      rows: {
        paceNow: "Current pace",
        tests: "Automated tests",
        decompiled: "Decompiled functions",
        prioritized: "Prioritized functions",
        tick: "World tick",
        subworlds: "Subworlds in assets",
        next: "Next milestone",
      },
      tickValue: "50 Hz now · 60 Hz target",
      subworldsValue: "44 playable in the PAK",
      testsValue: "world · gateway",
      nextValue: "ALC + movement diagnosis · no ETA",
    },
    versions: {
      title: "Versions",
      lead: "One version per milestone that changes what the system can do, since day 1 of the project.",
    },
    help: {
      title: "How to help",
      lead: "The project moves by evidence, not by hours. If any of these lines fits you, there is concrete, well-scoped work waiting.",
      supportTitle: "Support the project",
      supportBody:
        "Every analysis hour and every test session is paid in machine time and bandwidth. Progress is published here, with the same honesty for contributors and supporters.",
      supportCta: "Talk to the team",
    },
    footer: {
      brand: "Azoth — New World private server",
      data: "data: research/atlas · STATUS.md · git history — refreshed on every build",
    },
  },
} as const;

export function t(locale: Locale) {
  return ui[locale];
}
