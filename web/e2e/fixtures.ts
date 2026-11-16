import { test as base } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import type { PapelVersao } from "./papeis";

/** Espelha o JSON de `python -m tests.e2e.cenario`. */
export interface Manifesto {
  repo: string;
  repo_sem_checkout: string;
  versoes: Record<PapelVersao, string>;
  chamados: Record<PapelVersao, string>;
  arquivo_conflito: string;
  versao_nova: string;
  ambiente: Record<string, string>;
}

interface Daemon {
  manifesto: Manifesto;
  url: string;
}

const RAIZ_DO_PROJETO = resolve(import.meta.dirname, "..", "..");
const ESPERA_DAEMON_MS = 30_000;
const PASSO_ESPERA_MS = 200;

// O mesmo motivo do `unexport VIRTUAL_ENV` do Makefile: o uv usaria o interpretador vazado.
function ambienteBase(): NodeJS.ProcessEnv {
  const ambiente = { ...process.env };
  delete ambiente.VIRTUAL_ENV;
  return ambiente;
}

function uv(projeto: string, ...args: string[]): string[] {
  return ["run", "--project", projeto, ...args];
}

function montarCenario(projeto: string, raiz: string): Manifesto {
  const r = spawnSync(
    "uv",
    uv(projeto, "python", "-m", "tests.e2e.cenario", raiz),
    { cwd: projeto, env: ambienteBase(), encoding: "utf-8" },
  );
  if (r.status !== 0) throw new Error(`cenário falhou:\n${r.stderr}`);
  return JSON.parse(r.stdout) as Manifesto;
}

function portaLivre(): Promise<number> {
  return new Promise((ok, falha) => {
    const s = createServer();
    s.once("error", falha);
    s.listen(0, "127.0.0.1", () => {
      const endereco = s.address();
      s.close(() =>
        typeof endereco === "object" && endereco !== null
          ? ok(endereco.port)
          : falha(new Error("porta não atribuída")),
      );
    });
  });
}

async function esperar(url: string, processo: ChildProcess, stderr: () => string) {
  const limite = Date.now() + ESPERA_DAEMON_MS;
  while (Date.now() < limite) {
    if (processo.exitCode !== null)
      throw new Error(`daemon saiu (${processo.exitCode}):\n${stderr()}`);
    try {
      if ((await fetch(`${url}/api/repos`)).ok) return;
    } catch {
      // ainda não está ouvindo
    }
    await new Promise((r) => setTimeout(r, PASSO_ESPERA_MS));
  }
  throw new Error(`daemon não respondeu em ${ESPERA_DAEMON_MS} ms:\n${stderr()}`);
}

export const test = base.extend<{
  raizDoProjeto: string;
  daemon: Daemon;
  manifesto: Manifesto;
}>({
  raizDoProjeto: [RAIZ_DO_PROJETO, { option: true }],
  daemon: async ({ raizDoProjeto }, use) => {
    const tmp = await mkdtemp(join(tmpdir(), "monitor-versoes-e2e-"));
    const raiz = join(tmp, "cenario");
    const manifesto = montarCenario(raizDoProjeto, raiz);
    const porta = await portaLivre();
    // cwd na raiz do cenário: o `main()` carrega o `.env` do cwd com override.
    // detached: o `uv run` é um processo à parte, e matar só ele deixaria o daemon órfão.
    const processo = spawn(
      "uv",
      uv(
        raizDoProjeto,
        "monitor-versoes",
        "serve",
        "--sem-navegador",
        "--porta",
        String(porta),
      ),
      {
        cwd: raiz,
        env: { ...ambienteBase(), ...manifesto.ambiente },
        detached: true,
        stdio: ["ignore", "ignore", "pipe"],
      },
    );
    let stderr = "";
    processo.stderr?.on("data", (d: Buffer) => (stderr += d.toString()));
    const url = `http://127.0.0.1:${porta}`;
    try {
      await esperar(url, processo, () => stderr);
      await use({ manifesto, url });
    } finally {
      if (processo.pid !== undefined && processo.exitCode === null) {
        const fim = new Promise((r) => processo.once("exit", r));
        process.kill(-processo.pid, "SIGTERM");
        await fim;
      }
      await rm(tmp, { recursive: true, force: true });
    }
  },
  manifesto: async ({ daemon }, use) => use(daemon.manifesto),
  baseURL: async ({ daemon }, use) => use(daemon.url),
});

export { expect } from "@playwright/test";
