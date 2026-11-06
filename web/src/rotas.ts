const PADRAO = /^\/r\/([^/]+)(?:\/v\/([^/]+))?\/?$/;

export function caminhoDe(repo?: string, versao?: string): string {
  if (repo === undefined) return "/";
  const base = `/r/${encodeURIComponent(repo)}`;
  return versao === undefined
    ? base
    : `${base}/v/${encodeURIComponent(versao)}`;
}

export function lerCaminho(path: string): { repo?: string; versao?: string } {
  const m = PADRAO.exec(path);
  if (m === null) return {};
  const [, repo, versao] = m;
  return {
    ...(repo === undefined ? {} : { repo: decodeURIComponent(repo) }),
    ...(versao === undefined ? {} : { versao: decodeURIComponent(versao) }),
  };
}
