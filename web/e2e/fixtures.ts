import { test as base } from "@playwright/test";
import { execFileSync, spawn, spawnSync, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import type { PapelVersao } from "./papeis";

/** Espelha o JSON de `python -m tests.e2e.cenario`. */
export interface Manifesto {
  repo: string;
  repo_sem_checkout: string;
  clone: string;
  versoes: Record<PapelVersao, string>;
  chamados: Record<PapelVersao, string>;
  arquivo_conflito: string;
  versao_nova: string;
  ambiente: Record<string, string>;
}

interface Daemon {
  manifesto: Manifesto;
  url: string;
  raiz: string;
}

const RAIZ_DO_PROJETO = resolve(import.meta.dirname, "..", "..");
const ESPERA_DAEMON_MS = 30_000;
const PASSO_ESPERA_MS = 200;
const MONTAGEM_CENARIO_MS = 60_000;
const ENCERRAMENTO_DAEMON_MS = 5_000;

const ESPERA_TRAVA_MS = 30_000;
// Mesmo valor de `PRONTO` em tests/e2e/segurar_trava.py.
const SINAL_TRAVA_PRONTA = "pronto";

const NOME_MAPA = "mapa.json";

const pausa = (ms: number) => new Promise((r) => setTimeout(r, ms));

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
    {
      cwd: projeto,
      env: ambienteBase(),
      encoding: "utf-8",
      timeout: MONTAGEM_CENARIO_MS,
    },
  );
  if (r.status !== 0)
    throw new Error(`cenário falhou (${r.error ?? r.status}):\n${r.stderr}`);
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

async function esperar(
  url: string,
  processo: ChildProcess,
  falhaAoSubir: () => Error | undefined,
  stderr: () => string,
) {
  const limite = Date.now() + ESPERA_DAEMON_MS;
  while (Date.now() < limite) {
    const falha = falhaAoSubir();
    if (falha !== undefined)
      throw new Error(`daemon não subiu (${falha.message}):\n${stderr()}`);
    if (processo.exitCode !== null)
      throw new Error(`daemon saiu (${processo.exitCode}):\n${stderr()}`);
    try {
      if ((await fetch(`${url}/api/repos`)).ok) return;
    } catch {
      // ainda não está ouvindo
    }
    await pausa(PASSO_ESPERA_MS);
  }
  throw new Error(`daemon não respondeu em ${ESPERA_DAEMON_MS} ms:\n${stderr()}`);
}

async function encerrar(processo: ChildProcess): Promise<void> {
  const pid = processo.pid;
  if (pid === undefined || processo.exitCode !== null) return;
  const fim = new Promise((r) => processo.once("exit", r));
  process.kill(-pid, "SIGTERM");
  await Promise.race([fim, pausa(ENCERRAMENTO_DAEMON_MS)]);
  try {
    // O grupo inteiro: o `uv run` pode ter saído deixando o daemon para trás.
    process.kill(-pid, "SIGKILL");
  } catch {
    // ESRCH: o grupo já acabou.
  }
}

// Ambiente do cenário: o git não lê a config de quem roda.
export function git(manifesto: Manifesto, cwd: string, ...args: string[]): string {
  return execFileSync("git", args, {
    cwd,
    env: { ...process.env, ...manifesto.ambiente },
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

/** Dispara as inscrições vencidas, como o agendador do sistema faz. */
export function rodarInscricoes(manifesto: Manifesto, raiz: string): void {
  execFileSync("uv", uv(RAIZ_DO_PROJETO, "monitor-versoes", "inscricao", "rodar"), {
    cwd: raiz,
    env: { ...ambienteBase(), ...manifesto.ambiente },
    stdio: ["ignore", "pipe", "pipe"],
    timeout: MONTAGEM_CENARIO_MS,
  });
}

/** Segura o lock do clone num processo à parte; `soltar` libera. */
export interface TravaSegurada {
  soltar: () => Promise<void>;
}

export async function segurarTrava(manifesto: Manifesto, raiz: string): Promise<TravaSegurada> {
  const processo = spawn(
    "uv",
    uv(RAIZ_DO_PROJETO, "python", "-m", "tests.e2e.segurar_trava", manifesto.repo),
    {
      cwd: raiz,
      env: { ...ambienteBase(), ...manifesto.ambiente },
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const soltar = () => encerrar(processo);
  let stdout = "";
  let stderr = "";
  processo.stderr?.on("data", (d: Buffer) => (stderr += d.toString()));
  try {
    await new Promise<void>((ok, falha) => {
      const prazo = setTimeout(
        () => falha(new Error(`trava não ficou pronta em ${ESPERA_TRAVA_MS} ms:\n${stderr}`)),
        ESPERA_TRAVA_MS,
      );
      processo.once("error", falha);
      processo.once("exit", (codigo) =>
        falha(new Error(`auxiliar da trava saiu (${codigo}):\n${stderr}`)),
      );
      processo.stdout?.on("data", (d: Buffer) => {
        stdout += d.toString();
        if (stdout.includes(SINAL_TRAVA_PRONTA)) {
          clearTimeout(prazo);
          processo.removeAllListeners("exit");
          ok();
        }
      });
    });
  } catch (e) {
    await soltar();
    throw e;
  }
  return { soltar };
}

export const test = base.extend<{
  raizDoProjeto: string;
  daemon: Daemon;
  manifesto: Manifesto;
  raiz: string;
  adicionarChamado: (versao: string, chamado: string) => Promise<void>;
}>({
  raizDoProjeto: [RAIZ_DO_PROJETO, { option: true }],
  daemon: async ({ raizDoProjeto }, use) => {
    const tmp = await mkdtemp(join(tmpdir(), "monitor-versoes-e2e-"));
    try {
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
      let falhaAoSubir: Error | undefined;
      processo.once("error", (e) => (falhaAoSubir = e));
      let stderr = "";
      processo.stderr?.on("data", (d: Buffer) => (stderr += d.toString()));
      const url = `http://127.0.0.1:${porta}`;
      try {
        await esperar(url, processo, () => falhaAoSubir, () => stderr);
        await use({ manifesto, url, raiz });
      } finally {
        await encerrar(processo);
      }
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  },
  manifesto: async ({ daemon }, use) => use(daemon.manifesto),
  raiz: async ({ daemon }, use) => use(daemon.raiz),
  // O motor relê o mapa a cada consulta: muda o estado vivo sem tocar no snapshot.
  adicionarChamado: async ({ daemon }, use) =>
    use(async (versao, chamado) => {
      const arquivo = join(daemon.raiz, NOME_MAPA);
      const mapa = JSON.parse(await readFile(arquivo, "utf-8")) as Record<string, string[]>;
      mapa[versao] = [...(mapa[versao] ?? []), chamado];
      await writeFile(arquivo, JSON.stringify(mapa));
    }),
  baseURL: async ({ daemon }, use) => use(daemon.url),
});

export { expect } from "@playwright/test";
