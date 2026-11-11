import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Mesma porta de PORTA_PADRAO em motor/daemon/__init__.py.
const DAEMON = "http://127.0.0.1:8765";

// O editor de conflito é texto puro: as linguagens do Monaco e seus workers
// (≈10 MB, ts/css/html/json) e o cliente LSP ficam fora do build versionado.
const MONACO_SEM_USO =
  /^.*\/(languages\/(definitions|features)\/[^/]+\/register|external\/monaco-lsp-client\/out\/index)\.js$/;

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
