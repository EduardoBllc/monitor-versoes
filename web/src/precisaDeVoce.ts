import type { Execucao } from "./api/eventos";
import type { AtualizarResult, InscricaoVista } from "./api/tipos";
import { chaveVersao } from "./operacoes/chave";

export enum TipoPendencia {
  BLOQUEIO = "bloqueio",
  VERMELHOS = "vermelhos",
}

export interface ItemPendente {
  tipo: TipoPendencia;
  repo: string;
  versao: string;
  detalhe: string[];
  chave: string;
}

const CHAVE_STORAGE = "monitor-versoes:dispensados";

// As pendências do daemon são só os picks abertos (bloqueada ou vazia).
export function itensPendentes(
  pendencias: Execucao[],
  inscricoes: InscricaoVista[],
  dispensados: ReadonlySet<string>,
): ItemPendente[] {
  const bloqueios = pendencias.map((p) => ({
    tipo: TipoPendencia.BLOQUEIO,
    repo: p.repo,
    versao: p.versao,
    detalhe: (p.resultado as AtualizarResult).arquivos_conflito ?? [],
    chave: `${TipoPendencia.BLOQUEIO}:${chaveVersao(p.repo, p.versao)}`,
  }));
  const vermelhos = inscricoes.flatMap((i) =>
    i.ultima === null || i.ultima.vermelhos.length === 0
      ? []
      : [
          {
            tipo: TipoPendencia.VERMELHOS,
            repo: i.repo,
            versao: i.versao,
            detalhe: i.ultima.vermelhos,
            // Com a hora: os vermelhos de uma rodada nova voltam mesmo já dispensados antes.
            chave: `${TipoPendencia.VERMELHOS}:${chaveVersao(i.repo, i.versao)}:${i.ultima.hora}`,
          },
        ],
  );
  return [...bloqueios, ...vermelhos].filter((x) => !dispensados.has(x.chave));
}

// Sem storage (bloqueado, modo privado), o dispensado vale só nesta sessão.
const daSessao = new Set<string>();

export function lerDispensados(): Set<string> {
  try {
    const gravados = JSON.parse(localStorage.getItem(CHAVE_STORAGE) ?? "[]") as string[];
    return new Set([...gravados, ...daSessao]);
  } catch {
    return new Set(daSessao);
  }
}

export function dispensar(chave: string): Set<string> {
  daSessao.add(chave);
  const todos = lerDispensados();
  try {
    localStorage.setItem(CHAVE_STORAGE, JSON.stringify([...todos]));
  } catch {
    // Fica em `daSessao`.
  }
  return todos;
}
