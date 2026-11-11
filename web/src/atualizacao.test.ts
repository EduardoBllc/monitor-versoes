import { expect, it } from "vitest";
import { AtualizarStatus, EstadoExecucao, Operacao } from "./api/enums";
import type { Execucao } from "./api/eventos";
import type { AtualizarResult, CommitRef, VersionStatus } from "./api/tipos";
import {
  FaseAtualizacao,
  INICIAL,
  TipoEventoAtualizacao,
  acompanhaOcupado,
  proximo,
  type EstadoAtualizacao,
} from "./atualizacao";

const COMMIT = { hash_origem: "abc12345" } as CommitRef;
const LOTE = { faltantes: [COMMIT] } as VersionStatus;

const execucao = (
  operacao: Operacao,
  resultado: unknown,
  estado = EstadoExecucao.CONCLUIDA,
): Execucao => ({
  id: "x",
  repo: "r",
  versao: "1.0.0",
  operacao,
  estado,
  progresso: null,
  resultado,
  erro: null,
});
const atualizar = (status: AtualizarStatus) =>
  ({ status, blocked_commit: "abc12345deadbeef" }) as AtualizarResult;
const bloqueada = proximo(INICIAL, {
  tipo: TipoEventoAtualizacao.TERMINOU,
  execucao: execucao(Operacao.ATUALIZAR, atualizar(AtualizarStatus.BLOCKED)),
});

it("prévia com lote pergunta antes de aplicar", () => {
  const e = proximo(INICIAL, {
    tipo: TipoEventoAtualizacao.PREVIA_PRONTA,
    status: LOTE,
  });
  expect(e.fase).toBe(FaseAtualizacao.CONFIRMANDO);
});

it("prévia com lote vazio ou suspeitos vai direto ao status", () => {
  for (const status of [
    {} as VersionStatus,
    { faltantes: [COMMIT], suspeitos_conteudo: [COMMIT] } as VersionStatus,
  ]) {
    const e = proximo(INICIAL, {
      tipo: TipoEventoAtualizacao.PREVIA_PRONTA,
      status,
    });
    expect(e.fase).toBe(FaseAtualizacao.CONCLUIDA);
    expect(e.status).toBe(status);
  }
});

it("confirmar aplica e cancelar volta a ociosa", () => {
  const c = proximo(INICIAL, {
    tipo: TipoEventoAtualizacao.PREVIA_PRONTA,
    status: LOTE,
  });
  expect(proximo(c, { tipo: TipoEventoAtualizacao.CONFIRMOU }).fase).toBe(
    FaseAtualizacao.APLICANDO,
  );
  expect(proximo(c, { tipo: TipoEventoAtualizacao.CANCELOU }).fase).toBe(
    FaseAtualizacao.OCIOSA,
  );
});

it("aplicação termina em bloqueada, vazia ou concluída", () => {
  const fase = (s: AtualizarStatus) =>
    proximo(INICIAL, {
      tipo: TipoEventoAtualizacao.TERMINOU,
      execucao: execucao(Operacao.CONTINUAR, atualizar(s)),
    }).fase;
  expect(fase(AtualizarStatus.BLOCKED)).toBe(FaseAtualizacao.BLOQUEADA);
  expect(fase(AtualizarStatus.VAZIO)).toBe(FaseAtualizacao.VAZIA);
  expect(fase(AtualizarStatus.DONE)).toBe(FaseAtualizacao.CONCLUIDA);
});

it("continuar e abortar só em bloqueada/vazia, e falha devolve o bloqueio", () => {
  expect(proximo(INICIAL, { tipo: TipoEventoAtualizacao.CONTINUOU })).toBe(
    INICIAL,
  );
  expect(proximo(INICIAL, { tipo: TipoEventoAtualizacao.ABORTOU })).toBe(
    INICIAL,
  );
  const rodando = proximo(bloqueada, { tipo: TipoEventoAtualizacao.CONTINUOU });
  expect(rodando.fase).toBe(FaseAtualizacao.APLICANDO);
  const falhou = proximo(rodando, {
    tipo: TipoEventoAtualizacao.TERMINOU,
    execucao: execucao(Operacao.CONTINUAR, null, EstadoExecucao.FALHOU),
  });
  expect(falhou).toBe(bloqueada);
});

// Com falha: o pick foi resolvido fora da web e o daemon já esqueceu o bloqueio.
it.each([EstadoExecucao.CONCLUIDA, EstadoExecucao.FALHOU])(
  "abortar %s volta a ociosa",
  (estado) => {
    const abortando = proximo(bloqueada, {
      tipo: TipoEventoAtualizacao.ABORTOU,
    });
    const e = proximo(abortando, {
      tipo: TipoEventoAtualizacao.TERMINOU,
      execucao: execucao(Operacao.ABORTAR, null, estado),
    });
    expect(e.fase).toBe(FaseAtualizacao.OCIOSA);
  },
);

it("ocupado (409) em ociosa passa a acompanhar a execução", () => {
  expect(proximo(INICIAL, { tipo: TipoEventoAtualizacao.OCUPADO }).fase).toBe(
    FaseAtualizacao.APLICANDO,
  );
});

it.each([
  [EstadoExecucao.RODANDO, true],
  [EstadoExecucao.CONCLUIDA, false],
  [EstadoExecucao.FALHOU, false],
])("ocupado (409) com execução %s acompanha: %s", (estado, esperado) => {
  expect(acompanhaOcupado(execucao(Operacao.ATUALIZAR, null, estado))).toBe(
    esperado,
  );
});

it("ocupado (409) sem execução do daemon não acompanha", () => {
  expect(acompanhaOcupado(null)).toBe(false);
});

it("reconectou reconstitui a fase", () => {
  const re = (e: Execucao | null) =>
    proximo(INICIAL, { tipo: TipoEventoAtualizacao.RECONECTOU, execucao: e })
      .fase;
  const rodando = (o: Operacao) =>
    execucao(o, null, EstadoExecucao.RODANDO);
  expect(re(null)).toBe(FaseAtualizacao.OCIOSA);
  expect(re(rodando(Operacao.ATUALIZAR))).toBe(FaseAtualizacao.APLICANDO);
  expect(re(rodando(Operacao.CONTINUAR))).toBe(FaseAtualizacao.APLICANDO);
  expect(re(rodando(Operacao.PREVIA))).toBe(FaseAtualizacao.PREVIA);
  expect(
    re(execucao(Operacao.ATUALIZAR, atualizar(AtualizarStatus.BLOCKED))),
  ).toBe(FaseAtualizacao.BLOQUEADA);
  expect(
    re(execucao(Operacao.CONTINUAR, atualizar(AtualizarStatus.VAZIO))),
  ).toBe(FaseAtualizacao.VAZIA);
  expect(
    re(execucao(Operacao.ATUALIZAR, atualizar(AtualizarStatus.DONE))),
  ).toBe(FaseAtualizacao.OCIOSA);
});

it("reconectar pela pendência mantém o bloqueio depois de outra execução", () => {
  const re = (e: EstadoAtualizacao, x: Execucao | null) =>
    proximo(e, { tipo: TipoEventoAtualizacao.RECONECTOU, execucao: x });
  const pendencia = execucao(
    Operacao.ATUALIZAR,
    atualizar(AtualizarStatus.BLOCKED),
  );
  const reaberta = re(INICIAL, pendencia);
  expect(reaberta.fase).toBe(FaseAtualizacao.BLOQUEADA);
  const falhou = execucao(Operacao.CONTINUAR, null, EstadoExecucao.FALHOU);
  expect(re(reaberta, falhou)).toBe(reaberta);
  expect(re(reaberta, execucao(Operacao.VERIFICAR, LOTE))).toBe(reaberta);

  const continuando = re(
    reaberta,
    execucao(Operacao.CONTINUAR, null, EstadoExecucao.RODANDO),
  );
  expect(continuando.fase).toBe(FaseAtualizacao.APLICANDO);
  expect(
    proximo(continuando, { tipo: TipoEventoAtualizacao.TERMINOU, execucao: falhou }),
  ).toBe(reaberta);
});

it("criar com pick aberto deixa a versão nova bloqueada", () => {
  const criar = (s: AtualizarStatus) =>
    execucao(Operacao.CRIAR, atualizar(s));
  for (const tipo of [
    TipoEventoAtualizacao.TERMINOU,
    TipoEventoAtualizacao.RECONECTOU,
  ] as const) {
    expect(
      proximo(INICIAL, { tipo, execucao: criar(AtualizarStatus.BLOCKED) }).fase,
    ).toBe(FaseAtualizacao.BLOQUEADA);
    expect(
      proximo(INICIAL, { tipo, execucao: criar(AtualizarStatus.DONE) }).fase,
    ).toBe(FaseAtualizacao.OCIOSA);
  }
});
