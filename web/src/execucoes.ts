import { EstadoExecucao, Operacao, TipoErro } from "./api/enums";
import type { Execucao, Progresso } from "./api/eventos";
import type { VersionStatus } from "./api/tipos";

export interface Resultado {
  repo: string;
  versao: string;
  auditado: boolean;
  status: VersionStatus;
}

export interface EstadoExecucoes {
  readonly progresso: Readonly<Record<string, Progresso>>;
  readonly auditar: Readonly<Record<string, boolean>>;
}

export const SEM_EXECUCOES: EstadoExecucoes = { progresso: {}, auditar: {} };
export const PROGRESSO_INICIAL: Progresso = {
  fase: "iniciando",
  feito: 0,
  total: 0,
};

export const estaRodando = (e: EstadoExecucoes, repo: string): boolean =>
  repo in e.progresso;

// `seguir` é falso quando o repo já tem um acompanhamento aberto: nunca abrir um segundo.
export function iniciar(
  e: EstadoExecucoes,
  repo: string,
  auditar = false,
): { estado: EstadoExecucoes; seguir: boolean } {
  if (estaRodando(e, repo)) return { estado: e, seguir: false };
  return {
    estado: {
      progresso: { ...e.progresso, [repo]: PROGRESSO_INICIAL },
      auditar: { ...e.auditar, [repo]: auditar },
    },
    seguir: true,
  };
}

export function progredir(
  e: EstadoExecucoes,
  repo: string,
  p: Progresso,
): EstadoExecucoes {
  return estaRodando(e, repo)
    ? { ...e, progresso: { ...e.progresso, [repo]: p } }
    : e;
}

const sem = <T>(
  r: Readonly<Record<string, T>>,
  repo: string,
): Record<string, T> =>
  Object.fromEntries(Object.entries(r).filter(([nome]) => nome !== repo));

export function terminar(e: EstadoExecucoes, repo: string): EstadoExecucoes {
  return { progresso: sem(e.progresso, repo), auditar: sem(e.auditar, repo) };
}

export enum TipoEfeito {
  ERRO = "erro",
  RESULTADO = "resultado",
  NAVEGAR = "navegar",
  AVISAR = "avisar",
}

export type Efeito =
  | { tipo: TipoEfeito.ERRO; tipoErro: TipoErro; mensagem: string }
  | { tipo: TipoEfeito.RESULTADO; resultado: Resultado }
  | { tipo: TipoEfeito.NAVEGAR; repo: string; versao: string }
  | { tipo: TipoEfeito.AVISAR; mensagem: string };

// Só age na tela quando o repo da execução ainda é o selecionado; senão vira aviso.
export function concluir(
  e: EstadoExecucoes,
  fim: Execucao,
  selecionado: string | undefined,
): Efeito | null {
  if (fim.estado === EstadoExecucao.FALHOU) {
    return {
      tipo: TipoEfeito.ERRO,
      tipoErro: fim.erro?.tipo ?? TipoErro.INTERNO,
      mensagem: fim.erro?.mensagem ?? "operação falhou",
    };
  }
  const aqui = fim.repo === selecionado;
  if (fim.operacao === Operacao.VERIFICAR) {
    if (!aqui)
      return {
        tipo: TipoEfeito.AVISAR,
        mensagem: `verificação de ${fim.repo} ${fim.versao} terminou`,
      };
    return {
      tipo: TipoEfeito.RESULTADO,
      resultado: {
        repo: fim.repo,
        versao: fim.versao,
        auditado: e.auditar[fim.repo] ?? false,
        status: fim.resultado as VersionStatus,
      },
    };
  }
  if (fim.operacao === Operacao.CRIAR) {
    if (!aqui)
      return {
        tipo: TipoEfeito.AVISAR,
        mensagem: `versão ${fim.versao} criada em ${fim.repo}`,
      };
    return { tipo: TipoEfeito.NAVEGAR, repo: fim.repo, versao: fim.versao };
  }
  return null;
}
