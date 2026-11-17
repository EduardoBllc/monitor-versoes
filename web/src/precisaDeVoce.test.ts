import { afterEach, expect, it, vi } from "vitest";
import {
  AtualizarStatus,
  Desfecho,
  EstadoExecucao,
  Operacao,
} from "./api/enums";
import type { Execucao } from "./api/eventos";
import type { InscricaoVista } from "./api/tipos";
import {
  TipoPendencia,
  dispensar,
  itensPendentes,
  lerDispensados,
} from "./precisaDeVoce";

const REPO = "app";
const VERSAO = "1.2.0";
const ARQUIVO = "x.py";
const VERMELHO = "123";
const HORA = "2026-01-01T10:00:00Z";
const NADA = new Set<string>();

const bloqueio: Execucao = {
  id: "e1",
  repo: REPO,
  versao: VERSAO,
  operacao: Operacao.ATUALIZAR,
  estado: EstadoExecucao.CONCLUIDA,
  progresso: null,
  resultado: { status: AtualizarStatus.BLOCKED, arquivos_conflito: [ARQUIVO] },
  erro: null,
};

const comVermelhos: InscricaoVista = {
  repo: REPO,
  versao: VERSAO,
  intervalo: "1h",
  ultima: {
    hora: HORA,
    desfecho: Desfecho.NADA,
    desfecho_aviso: Desfecho.NADA,
    vermelhos: [VERMELHO],
    mensagem: "",
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

it("bloqueio vira item com link da versão", () => {
  expect(itensPendentes([bloqueio], [], NADA)).toEqual([
    expect.objectContaining({
      tipo: TipoPendencia.BLOQUEIO,
      repo: REPO,
      versao: VERSAO,
      detalhe: [ARQUIVO],
    }),
  ]);
});

it("vermelhos da última rodada viram item", () => {
  expect(itensPendentes([], [comVermelhos], NADA)).toEqual([
    expect.objectContaining({
      tipo: TipoPendencia.VERMELHOS,
      repo: REPO,
      versao: VERSAO,
      detalhe: [VERMELHO],
    }),
  ]);
});

it("dispensado não aparece", () => {
  const [item] = itensPendentes([], [comVermelhos], NADA);
  expect(itensPendentes([], [comVermelhos], new Set([item!.chave]))).toEqual([]);
});

it("dispensados sem storage não lança", () => {
  const falha = () => {
    throw new Error("sem storage");
  };
  vi.stubGlobal("localStorage", { getItem: falha, setItem: falha });
  const [item] = itensPendentes([], [comVermelhos], NADA);
  expect(dispensar(item!.chave).has(item!.chave)).toBe(true);
  expect(lerDispensados().has(item!.chave)).toBe(true);
});
