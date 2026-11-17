import type { ChamadoIndexado, RepoOption, VersaoListada } from "../api/tipos";
import { Pagina, type Rota } from "../rotas";

export enum TipoAcao {
  REPO = "repo",
  VERSAO = "versao",
  CHAMADO = "chamado",
}

export interface AcaoPaleta {
  id: string;
  tipo: TipoAcao;
  rotulo: string;
  descricao: string;
  rota: Rota;
}

const PREFIXO_CHAMADO = "#";
const SEPARADOR = " · ";

export function acoesDaPaleta(
  repos: RepoOption[],
  versoes: Record<string, VersaoListada[]>,
  chamados: ChamadoIndexado[],
): AcaoPaleta[] {
  const doRepo = repos.map((r) => ({
    id: `${TipoAcao.REPO}:${r.nome}`,
    tipo: TipoAcao.REPO,
    rotulo: r.nome,
    descricao: "repo",
    rota: { pagina: Pagina.REPO, repo: r.nome } as Rota,
  }));
  const dasVersoes = repos.flatMap((r) =>
    (versoes[r.nome] ?? []).map((v) => ({
      id: `${TipoAcao.VERSAO}:${r.nome}:${v.numero}`,
      tipo: TipoAcao.VERSAO,
      rotulo: v.numero,
      descricao: `versão${SEPARADOR}${r.nome}`,
      rota: { pagina: Pagina.VERSAO, repo: r.nome, versao: v.numero } as Rota,
    })),
  );
  const dosChamados = chamados.map((c) => ({
    id: `${TipoAcao.CHAMADO}:${c.repo}:${c.versao}:${c.chamado}`,
    tipo: TipoAcao.CHAMADO,
    rotulo: `${PREFIXO_CHAMADO}${c.chamado}`,
    descricao: `${c.versao}${SEPARADOR}${c.repo}`,
    rota: { pagina: Pagina.VERSAO, repo: c.repo, versao: c.versao } as Rota,
  }));
  return [...doRepo, ...dasVersoes, ...dosChamados];
}
