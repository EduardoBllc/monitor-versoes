import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Mesma porta de PORTA_PADRAO em motor/daemon/__init__.py.
const DAEMON = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": DAEMON } },
  build: { outDir: "../motor/daemon/static", emptyOutDir: true },
});
