import tailwindcss from "@tailwindcss/vite";

// --base /Azoth overrides the default "/" (used by the Pages workflow).
// Git-Bash on Windows converts "/Azoth" to "C:/Program Files/Git/Azoth";
// detect that case and recover the original POSIX path.
function pagesBase() {
  const raw = String(process.env.PAGES_BASE || "/").trim();
  if (!raw) return "/";
  const msys = raw.match(/^[A-Za-z]:[/]Program Files[/]Git[/](.+)$/);
  if (msys) return "/" + msys[1].replace(/[/]+$/, "");
  if (raw.startsWith("/")) return raw.replace(/[/]+$/, "") || "/";
  return "/" + raw.replace(/[/]+$/, "");
}

const base = pagesBase();

export default {
  base,
  trailingSlash: "ignore",
  vite: {
    plugins: [tailwindcss()],
  },
};
