import type { OrfaoDaVersao } from "./api/tipos";

const versoes = (repo: string, versao: string): string =>
  `/api/repos/${encodeURIComponent(repo)}/versoes/${encodeURIComponent(versao)}`;

export function caminhoOrfaos(repo: string, versao: string): string {
  return `${versoes(repo, versao)}/orfaos`;
}

export function caminhoJulgamento(
  repo: string,
  versao: string,
  hash: string,
): string {
  return `${caminhoOrfaos(repo, versao)}/${encodeURIComponent(hash)}/julgamento`;
}

// O mesmo rótulo da CLI e da TUI, sem o motivo (que tem coluna própria).
export function rotuloJulgamento(o: OrfaoDaVersao): string {
  const j = o.julgamento;
  if (j === null) return "pendente";
  return j.chamado == null ? "nenhum" : `pertence a ${j.chamado}`;
}
