import { TipoArquivo } from "./api/enums";
import type { PropostaDeBloco } from "./api/tipos";
import { EstadoBloco } from "./conflito";

export type EstadoPropostas = {
  geracao: number;
  emAndamento: boolean;
  pendentes: ReadonlyMap<number, PropostaDeBloco>;
};

export const SEM_PROPOSTAS: EstadoPropostas = {
  geracao: 0,
  emAndamento: false,
  pendentes: new Map(),
};

export const mostraGatilhos = (
  disponivel: boolean,
  tipo: TipoArquivo,
  resolvido: boolean,
): boolean => disponivel && tipo === TipoArquivo.CONTEUDO && !resolvido;

export enum TituloLente {
  SUGERIR = "$(sparkle) Sugerir",
  SUGERINDO = "$(sparkle) Sugerindo…",
}

export function lenteSugerir(
  estado: EstadoBloco,
  emAndamento: boolean,
): { titulo: TituloLente; acionavel: boolean } | null {
  if (estado !== EstadoBloco.ABERTO) return null;
  return emAndamento
    ? { titulo: TituloLente.SUGERINDO, acionavel: false }
    : { titulo: TituloLente.SUGERIR, acionavel: true };
}

export function iniciar(
  e: EstadoPropostas,
  estados: readonly EstadoBloco[],
  alvo: number | null,
): { estado: EstadoPropostas; geracao: number; ordens: number[] } | null {
  if (e.emAndamento) return null;
  const ordens = estados.flatMap((s, k) =>
    s === EstadoBloco.ABERTO && (alvo === null || alvo === k) ? [k] : [],
  );
  if (ordens.length === 0) return null;
  return { estado: { ...e, emAndamento: true }, geracao: e.geracao, ordens };
}

const soAbertas = (
  pendentes: ReadonlyMap<number, PropostaDeBloco>,
  estados: readonly EstadoBloco[],
) =>
  new Map([...pendentes].filter(([k]) => estados[k] === EstadoBloco.ABERTO));

export function receber(
  e: EstadoPropostas,
  geracao: number,
  recebidas: readonly PropostaDeBloco[],
  estados: readonly EstadoBloco[],
): EstadoPropostas {
  if (geracao !== e.geracao) return e;
  const pendentes = new Map(e.pendentes);
  for (const p of recebidas) pendentes.set(p.ordem, p);
  return { ...e, emAndamento: false, pendentes: soAbertas(pendentes, estados) };
}

export const falhar = (e: EstadoPropostas, geracao: number): EstadoPropostas =>
  geracao === e.geracao ? { ...e, emAndamento: false } : e;

export const vigente = (e: EstadoPropostas, geracao: number): boolean =>
  geracao === e.geracao;

export function descartar(e: EstadoPropostas, ordem: number): EstadoPropostas {
  const pendentes = new Map(e.pendentes);
  pendentes.delete(ordem);
  return { ...e, pendentes };
}

export const podar = (
  e: EstadoPropostas,
  estados: readonly EstadoBloco[],
): EstadoPropostas => ({ ...e, pendentes: soAbertas(e.pendentes, estados) });

export const invalidar = (e: EstadoPropostas): EstadoPropostas => ({
  geracao: e.geracao + 1,
  emAndamento: false,
  pendentes: new Map(),
});

// Sem a quebra final, o Aplicar colaria a última linha na seguinte ao bloco.
export const trechoDaProposta = (conteudo: string): string =>
  conteudo === "" || conteudo.endsWith("\n") ? conteudo : conteudo + "\n";
