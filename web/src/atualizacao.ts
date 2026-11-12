import {
  AtualizarStatus,
  EstadoExecucao,
  Operacao,
  assertNever,
} from "./api/enums";
import type { Execucao } from "./api/eventos";
import type { AtualizarResult, VersionStatus } from "./api/tipos";

export enum FaseAtualizacao {
  OCIOSA = "ociosa",
  PREVIA = "previa",
  CONFIRMANDO = "confirmando",
  APLICANDO = "aplicando",
  BLOQUEADA = "bloqueada",
  VAZIA = "vazia",
  CONCLUIDA = "concluida",
}

export enum TipoEventoAtualizacao {
  INICIOU = "iniciou",
  PREVIA_PRONTA = "previa_pronta",
  CONFIRMOU = "confirmou",
  CANCELOU = "cancelou",
  CONTINUOU = "continuou",
  ABORTOU = "abortou",
  FECHOU = "fechou",
  TERMINOU = "terminou",
  OCUPADO = "ocupado",
  RECONECTOU = "reconectou",
}

// Fase por repo+versão. `anterior` é para onde volta se a operação em andamento falhar.
export interface EstadoAtualizacao {
  readonly fase: FaseAtualizacao;
  readonly status: VersionStatus | null;
  readonly resultado: AtualizarResult | null;
  readonly anterior: EstadoAtualizacao | null;
}

export type Evento =
  | { tipo: TipoEventoAtualizacao.INICIOU }
  | { tipo: TipoEventoAtualizacao.PREVIA_PRONTA; status: VersionStatus }
  | { tipo: TipoEventoAtualizacao.CONFIRMOU }
  | { tipo: TipoEventoAtualizacao.CANCELOU }
  | { tipo: TipoEventoAtualizacao.CONTINUOU }
  | { tipo: TipoEventoAtualizacao.ABORTOU }
  | { tipo: TipoEventoAtualizacao.FECHOU }
  | { tipo: TipoEventoAtualizacao.TERMINOU; execucao: Execucao }
  | { tipo: TipoEventoAtualizacao.OCUPADO }
  | { tipo: TipoEventoAtualizacao.RECONECTOU; execucao: Execucao | null };

// Eventos sem payload, os que a tela dispara direto.
export type EventoSimples = Extract<
  Evento,
  { tipo: TipoEventoAtualizacao.INICIOU | TipoEventoAtualizacao.CONFIRMOU | TipoEventoAtualizacao.CANCELOU | TipoEventoAtualizacao.CONTINUOU | TipoEventoAtualizacao.ABORTOU | TipoEventoAtualizacao.FECHOU }
>["tipo"];

export const INICIAL: EstadoAtualizacao = {
  fase: FaseAtualizacao.OCIOSA,
  status: null,
  resultado: null,
  anterior: null,
};

const em = (
  fase: FaseAtualizacao,
  extra: Partial<EstadoAtualizacao> = {},
): EstadoAtualizacao => ({ ...INICIAL, fase, ...extra });

const emAndamento = (e: EstadoAtualizacao): boolean =>
  e.fase === FaseAtualizacao.PREVIA || e.fase === FaseAtualizacao.APLICANDO;
const volta = (e: EstadoAtualizacao): EstadoAtualizacao =>
  emAndamento(e) ? (e.anterior ?? INICIAL) : e;
const pendente = (e: EstadoAtualizacao): boolean =>
  e.fase === FaseAtualizacao.BLOQUEADA || e.fase === FaseAtualizacao.VAZIA;

// Lote vazio ou com suspeitos não pergunta: o motor recusaria o sim, então só mostra o status.
function previaPronta(status: VersionStatus): EstadoAtualizacao {
  const semPergunta =
    !status.faltantes?.length || (status.suspeitos_conteudo?.length ?? 0) > 0;
  return em(
    semPergunta ? FaseAtualizacao.CONCLUIDA : FaseAtualizacao.CONFIRMANDO,
    { status },
  );
}

const depoisDeAplicar = (r: AtualizarResult): EstadoAtualizacao => {
  // O esquema gerado tipa o status como 0|1|2; o cast alinha ao enum para o switch exaustivo.
  switch (r.status as AtualizarStatus) {
    case AtualizarStatus.BLOCKED:
      return em(FaseAtualizacao.BLOQUEADA, { resultado: r });
    case AtualizarStatus.VAZIO:
      return em(FaseAtualizacao.VAZIA, { resultado: r });
    case AtualizarStatus.DONE:
      return em(FaseAtualizacao.CONCLUIDA, { resultado: r });
    default:
      return assertNever(r.status as never);
  }
};

// Num 409, só há o que acompanhar se o daemon roda algo no repo; senão o lock é de
// outro processo (CLI, TUI ou inscrição).
export const acompanhaOcupado = (x: Execucao | null): boolean =>
  x?.estado === EstadoExecucao.RODANDO;

// Atualizar, continuar e criar concluídos sem DONE deixam o cherry-pick aberto.
export const pickAberto = (x: Execucao): boolean =>
  x.estado === EstadoExecucao.CONCLUIDA &&
  (x.operacao === Operacao.ATUALIZAR ||
    x.operacao === Operacao.CONTINUAR ||
    x.operacao === Operacao.CRIAR) &&
  (x.resultado as AtualizarResult).status !== AtualizarStatus.DONE;

function terminou(e: EstadoAtualizacao, x: Execucao): EstadoAtualizacao {
  // Abortar que falha também sai do bloqueio, como no daemon: o pick pode ter sido
  // resolvido fora da web, e um pick ainda aberto reaparece no próximo atualizar.
  if (x.estado === EstadoExecucao.FALHOU && x.operacao !== Operacao.ABORTAR)
    return volta(e);
  switch (x.operacao) {
    case Operacao.PREVIA:
      return previaPronta(x.resultado as VersionStatus);
    case Operacao.ATUALIZAR:
    case Operacao.CONTINUAR:
      return depoisDeAplicar(x.resultado as AtualizarResult);
    case Operacao.ABORTAR:
      return INICIAL;
    case Operacao.CRIAR:
      // Criar termina num atualizar: só o pick aberto muda a fase da versão nova.
      return pickAberto(x) ? depoisDeAplicar(x.resultado as AtualizarResult) : volta(e);
    case Operacao.VERIFICAR:
      return volta(e);
    default:
      return assertNever(x.operacao);
  }
}

function reconectou(
  e: EstadoAtualizacao,
  x: Execucao | null,
): EstadoAtualizacao {
  if (x === null || x.estado === EstadoExecucao.FALHOU) return volta(e);
  if (x.estado === EstadoExecucao.RODANDO) {
    switch (x.operacao) {
      case Operacao.PREVIA:
        return em(FaseAtualizacao.PREVIA);
      case Operacao.ATUALIZAR:
      case Operacao.CONTINUAR:
      case Operacao.ABORTAR:
        return em(FaseAtualizacao.APLICANDO, {
          anterior: emAndamento(e) ? e.anterior : e,
        });
      case Operacao.VERIFICAR:
      case Operacao.CRIAR:
        return e;
      default:
        return assertNever(x.operacao);
    }
  }
  // Concluída: só um pick pendente interessa ao reabrir a página.
  return pickAberto(x) ? depoisDeAplicar(x.resultado as AtualizarResult) : e;
}

export function proximo(e: EstadoAtualizacao, ev: Evento): EstadoAtualizacao {
  switch (ev.tipo) {
    case TipoEventoAtualizacao.INICIOU:
      return em(FaseAtualizacao.PREVIA);
    case TipoEventoAtualizacao.PREVIA_PRONTA:
      return previaPronta(ev.status);
    case TipoEventoAtualizacao.CONFIRMOU:
      return e.fase === FaseAtualizacao.CONFIRMANDO
        ? em(FaseAtualizacao.APLICANDO)
        : e;
    case TipoEventoAtualizacao.CANCELOU:
      return e.fase === FaseAtualizacao.CONFIRMANDO ? INICIAL : e;
    case TipoEventoAtualizacao.CONTINUOU:
    case TipoEventoAtualizacao.ABORTOU:
      return pendente(e) ? em(FaseAtualizacao.APLICANDO, { anterior: e }) : e;
    case TipoEventoAtualizacao.FECHOU:
      return e.fase === FaseAtualizacao.CONCLUIDA ? INICIAL : e;
    case TipoEventoAtualizacao.TERMINOU:
      return terminou(e, ev.execucao);
    case TipoEventoAtualizacao.OCUPADO:
      return em(FaseAtualizacao.APLICANDO, {
        anterior: emAndamento(e) ? e.anterior : e,
      });
    case TipoEventoAtualizacao.RECONECTOU:
      return reconectou(e, ev.execucao);
    default:
      return assertNever(ev);
  }
}
