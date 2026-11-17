export enum Pagina {
  INICIO = "inicio",
  REPO = "repo",
  VERSAO = "versao",
  CONFIG = "config",
}

export type Rota =
  | { pagina: Pagina.INICIO }
  | { pagina: Pagina.CONFIG }
  | { pagina: Pagina.REPO; repo: string }
  | { pagina: Pagina.VERSAO; repo: string; versao: string };

const CAMINHO_INICIO = "/";
const CAMINHO_CONFIG = "/config";
const PADRAO_REPO = /^\/r\/([^/]+)(?:\/v\/([^/]+))?\/?$/;

export function lerRota(path: string): Rota {
  if (path === CAMINHO_CONFIG) return { pagina: Pagina.CONFIG };
  const m = PADRAO_REPO.exec(path);
  if (m?.[1] === undefined) return { pagina: Pagina.INICIO };
  const repo = decodeURIComponent(m[1]);
  return m[2] === undefined
    ? { pagina: Pagina.REPO, repo }
    : { pagina: Pagina.VERSAO, repo, versao: decodeURIComponent(m[2]) };
}

export function caminhoDa(rota: Rota): string {
  switch (rota.pagina) {
    case Pagina.INICIO:
      return CAMINHO_INICIO;
    case Pagina.CONFIG:
      return CAMINHO_CONFIG;
    case Pagina.REPO:
      return `/r/${encodeURIComponent(rota.repo)}`;
    case Pagina.VERSAO:
      return `${caminhoDa({ pagina: Pagina.REPO, repo: rota.repo })}/v/${encodeURIComponent(rota.versao)}`;
  }
}

/** Repo e versão da rota, quando ela tem. */
export function alvoDa(rota: Rota): { repo?: string; versao?: string } {
  if (rota.pagina === Pagina.REPO) return { repo: rota.repo };
  if (rota.pagina === Pagina.VERSAO) return { repo: rota.repo, versao: rota.versao };
  return {};
}
