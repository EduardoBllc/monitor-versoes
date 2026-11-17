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
const HORA_SEGUINTE = "2026-01-01T11:00:00Z";
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

const vazia: Execucao = {
  ...bloqueio,
  resultado: { status: AtualizarStatus.VAZIO, arquivos_conflito: [] },
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

it("pick vazio vira item à espera do registro, não de conflito", () => {
  expect(itensPendentes([vazia], [], NADA)).toEqual([
    expect.objectContaining({ tipo: TipoPendencia.VAZIA, repo: REPO, versao: VERSAO }),
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
  expect(dispensar(item!.chave, [item!.chave]).has(item!.chave)).toBe(true);
  expect(lerDispensados().has(item!.chave)).toBe(true);
});

it("dispensar esquece o que já não está pendente", () => {
  const memoria = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => memoria.get(k) ?? null,
    setItem: (k: string, v: string) => memoria.set(k, v),
  });
  const [antigo] = itensPendentes([], [comVermelhos], NADA);
  const [novo] = itensPendentes([], [{ ...comVermelhos, ultima: { ...comVermelhos.ultima!, hora: HORA_SEGUINTE } }], NADA);
  dispensar(antigo!.chave, [antigo!.chave]);
  expect([...dispensar(novo!.chave, [novo!.chave])]).toEqual([novo!.chave]);
});
