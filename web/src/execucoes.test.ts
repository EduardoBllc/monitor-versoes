import { expect, it } from "vitest";
import { EstadoExecucao, Operacao } from "./api/enums";
import type { Execucao } from "./api/eventos";
import {
  SEM_EXECUCOES,
  TipoEfeito,
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
