import { expect, it } from "vitest";
import { AtualizarStatus, EstadoExecucao, Operacao, TipoErro } from "./api/enums";
import type { Execucao } from "./api/eventos";
import {
  SEM_EXECUCOES,
  TipoEfeito,
  avisoPendencia,
  concluir,
  estaRodando,
  iniciar,
  terminar,
} from "./execucoes";
import type { VersionStatus } from "./api/tipos";

const STATUS = { verde: true, estado_integro: true } as VersionStatus;

const fim = (repo: string, operacao: Operacao): Execucao => ({
  id: "x",
  repo,
  versao: "14.0.0",
  operacao,
  estado: EstadoExecucao.CONCLUIDA,
  progresso: null,
  resultado: STATUS,
  erro: null,
});

it("seguir o mesmo repo duas vezes não abre segundo acompanhamento", () => {
  const a = iniciar(SEM_EXECUCOES, "A");
  expect(a.seguir).toBe(true);
  const b = iniciar(a.estado, "A");
  expect(b.seguir).toBe(false);
  expect(iniciar(a.estado, "B").seguir).toBe(true);
  expect(estaRodando(terminar(a.estado, "A"), "A")).toBe(false);
});

it("criar terminando em outro repo avisa e não navega", () => {
  const e = iniciar(SEM_EXECUCOES, "A").estado;
  expect(concluir(e, fim("A", Operacao.CRIAR), "B")?.tipo).toBe(
    TipoEfeito.AVISAR,
  );
  expect(concluir(e, fim("A", Operacao.CRIAR), "A")?.tipo).toBe(
    TipoEfeito.NAVEGAR,
  );
});

it("resultado carrega repo, versão e auditar", () => {
  const e = iniciar(SEM_EXECUCOES, "A", true).estado;
  expect(concluir(e, fim("A", Operacao.VERIFICAR), "A")).toEqual({
    tipo: TipoEfeito.RESULTADO,
    resultado: { repo: "A", versao: "14.0.0", auditado: true, status: STATUS },
  });
  expect(concluir(e, fim("A", Operacao.VERIFICAR), "B")?.tipo).toBe(
    TipoEfeito.AVISAR,
  );
});

const atualizacao = (
  operacao: Operacao,
  status: AtualizarStatus,
  versao = "14.0.0",
): Execucao => ({
  ...fim("A", operacao),
  versao,
  resultado: { status },
});

it("atualização fora da tela avisa com repo, versão e desfecho", () => {
  const e = SEM_EXECUCOES;
  const bloq = concluir(
    e,
    atualizacao(Operacao.ATUALIZAR, AtualizarStatus.BLOCKED),
    "B",
    "14.0.0",
  );
  expect(bloq).toEqual({
    tipo: TipoEfeito.AVISAR,
    mensagem: "A 14.0.0: atualização bloqueada",
    destino: { repo: "A", versao: "14.0.0" },
  });
  // mesma repo, outra versão na tela
  const outra = concluir(
    e,
    atualizacao(Operacao.CONTINUAR, AtualizarStatus.DONE),
    "A",
    "15.0.0",
  );
  expect(outra).toEqual({
    tipo: TipoEfeito.AVISAR,
    mensagem: "A 14.0.0: atualização concluída",
  });
  expect(
    concluir(e, atualizacao(Operacao.ABORTAR, AtualizarStatus.DONE), "B")
      ?.tipo,
  ).toBe(TipoEfeito.AVISAR);
  // na tela: o estado da atualização já mostra
  expect(
    concluir(
      e,
      atualizacao(Operacao.ATUALIZAR, AtualizarStatus.BLOCKED),
      "A",
      "14.0.0",
    ),
  ).toBeNull();
});

it("atualização que falhou fora da tela nomeia repo e versão", () => {
  const falha: Execucao = {
    ...fim("A", Operacao.ATUALIZAR),
    estado: EstadoExecucao.FALHOU,
    erro: { tipo: TipoErro.MOTOR, mensagem: "boom" },
  };
  const ef = concluir(SEM_EXECUCOES, falha, "B");
  expect(ef).toMatchObject({ tipo: TipoEfeito.ERRO });
  expect(ef && "mensagem" in ef && ef.mensagem).toContain("A 14.0.0");
});

it("bloqueio de outra versão achado ao recarregar vira aviso persistente", () => {
  const bloq = atualizacao(Operacao.ATUALIZAR, AtualizarStatus.BLOCKED);
  expect(avisoPendencia(bloq, "15.0.0")).toMatchObject({
    tipo: TipoEfeito.AVISAR,
    destino: { repo: "A", versao: "14.0.0" },
  });
  expect(avisoPendencia(bloq, "14.0.0")).toBeNull();
  expect(
    avisoPendencia(
      atualizacao(Operacao.ATUALIZAR, AtualizarStatus.DONE),
      "15.0.0",
    ),
  ).toBeNull();
  expect(avisoPendencia(null, "15.0.0")).toBeNull();
});
