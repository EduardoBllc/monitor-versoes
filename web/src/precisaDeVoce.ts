import { AtualizarStatus } from "./api/enums";
import type { Execucao } from "./api/eventos";
import type { AtualizarResult, InscricaoVista } from "./api/tipos";
import { chaveVersao } from "./operacoes/chave";

export enum TipoPendencia {
  BLOQUEIO = "bloqueio",
  VAZIA = "vazia",
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
  const bloqueios = pendencias.map((p) => {
    // O esquema tipa o resultado de qualquer operação como unknown; pendência é de atualizar.
    const r = p.resultado as AtualizarResult | null;
    const tipo =
      r?.status === AtualizarStatus.VAZIO ? TipoPendencia.VAZIA : TipoPendencia.BLOQUEIO;
    return {
      tipo,
      repo: p.repo,
      versao: p.versao,
      detalhe: r?.arquivos_conflito ?? [],
      chave: `${tipo}:${chaveVersao(p.repo, p.versao)}`,
    };
  });
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

/** Dispensa a chave e esquece as que já não estão em `vigentes` (as pendências de agora). */
export function dispensar(chave: string, vigentes: readonly string[]): Set<string> {
  const todos = new Set([...lerDispensados(), chave].filter((c) => vigentes.includes(c)));
  daSessao.clear();
  for (const c of todos) daSessao.add(c);
  try {
    localStorage.setItem(CHAVE_STORAGE, JSON.stringify([...todos]));
  } catch {
    // Fica em `daSessao`.
  }
  return todos;
}
