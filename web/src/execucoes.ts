import {
  AtualizarStatus,
  EstadoExecucao,
  Operacao,
  TipoErro,
} from "./api/enums";
import type { Execucao, Progresso } from "./api/eventos";
import type { AtualizarResult, VersionStatus } from "./api/tipos";

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
  // `destino` marca o aviso que fica na tela até fechar, com atalho para a versão.
  | {
      tipo: TipoEfeito.AVISAR;
      mensagem: string;
      destino?: { repo: string; versao: string };
    };

const ehAtualizacao = (o: Operacao): boolean =>
  o === Operacao.PREVIA ||
  o === Operacao.ATUALIZAR ||
  o === Operacao.CONTINUAR ||
  o === Operacao.ABORTAR;

// Aviso de pick aberto (bloqueada/vazia) numa versão que não é a da tela.
export function avisoPendencia(
  fim: Execucao | null,
  versaoAtual: string | undefined,
): Efeito | null {
  if (
    fim === null ||
    fim.estado !== EstadoExecucao.CONCLUIDA ||
    fim.versao === versaoAtual ||
    (fim.operacao !== Operacao.ATUALIZAR && fim.operacao !== Operacao.CONTINUAR)
  )
    return null;
  const r = fim.resultado as AtualizarResult;
  if (r.status === AtualizarStatus.DONE) return null;
  return {
    tipo: TipoEfeito.AVISAR,
    mensagem: `${fim.repo} ${fim.versao}: ${
      r.status === AtualizarStatus.BLOCKED
        ? "atualização bloqueada"
        : "resolução sem alteração"
    }`,
    destino: { repo: fim.repo, versao: fim.versao },
  };
}

function avisoAtualizacao(fim: Execucao): Efeito {
  const destino = { repo: fim.repo, versao: fim.versao };
  const nome = `${fim.repo} ${fim.versao}`;
  if (fim.operacao === Operacao.ABORTAR)
    return { tipo: TipoEfeito.AVISAR, mensagem: `${nome}: atualização abortada` };
  if (fim.operacao === Operacao.PREVIA)
    return {
      tipo: TipoEfeito.AVISAR,
      mensagem: `${nome}: prévia pronta`,
      destino,
    };
  const pendencia = avisoPendencia(fim, undefined);
  return (
    pendencia ?? {
      tipo: TipoEfeito.AVISAR,
      mensagem: `${nome}: atualização concluída`,
    }
  );
}

// Só age na tela quando o repo da execução ainda é o selecionado; senão vira aviso.
export function concluir(
  e: EstadoExecucoes,
  fim: Execucao,
  selecionado: string | undefined,
  versaoSelecionada?: string,
): Efeito | null {
  const aqui = fim.repo === selecionado;
  const naTela = aqui && fim.versao === versaoSelecionada;
  if (fim.estado === EstadoExecucao.FALHOU) {
    const mensagem = fim.erro?.mensagem ?? "operação falhou";
    return {
      tipo: TipoEfeito.ERRO,
      tipoErro: fim.erro?.tipo ?? TipoErro.INTERNO,
      mensagem:
        ehAtualizacao(fim.operacao) && !naTela
          ? `${fim.repo} ${fim.versao}: falhou — ${mensagem}`
          : mensagem,
    };
  }
  if (ehAtualizacao(fim.operacao)) return naTela ? null : avisoAtualizacao(fim);
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
