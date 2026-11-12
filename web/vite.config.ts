import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Mesma porta de PORTA_PADRAO em motor/daemon/__init__.py.
const DAEMON = "http://127.0.0.1:8765";

// O editor de conflito só colore: entram os tokenizadores monarch (sem worker)
// desta lista e o JSON com o worker dele. O resto das linguagens, os serviços de
// TS/CSS/HTML (≈10 MB com os workers) e o cliente LSP ficam fora do build
// versionado. Extensão fora da lista abre como texto puro.
const TOKENIZADORES = [
  "python",
  "javascript",
  "typescript",
  "css",
  "scss",
  "less",
  "html",
  "xml",
  "yaml",
  "sql",
  "mysql",
  "pgsql",
  "shell",
  "markdown",
  "ini",
  "dockerfile",
];
const MONACO_SEM_USO = new RegExp(
  "^.*/(languages/definitions/(?!(?:" +
    TOKENIZADORES.join("|") +
    ")/)[^/]+/register|languages/features/(?:css|html|typescript)/register|external/monaco-lsp-client/out/index)\\.js$",
);

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      {
        find: MONACO_SEM_USO,
        replacement: fileURLToPath(new URL("src/vazio.ts", import.meta.url)),
      },
    ],
  },
  server: { proxy: { "/api": DAEMON } },
  build: { outDir: "../motor/daemon/static", emptyOutDir: true },
});
