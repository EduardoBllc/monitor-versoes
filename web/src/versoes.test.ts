import { expect, it } from "vitest";
import type { VersaoListada } from "./api/tipos";
import { emAberto, juntarVersoes } from "./versoes";

const ABERTA = "1.1.0";
const LIBERADA = "1.0.0";
const SO_NO_FETCH = "1.2.0";
const ANTES = "2026-01-01T10:00:00Z";
const DEPOIS = "2026-01-01T11:00:00Z";
const PRESENTES = 3;

const versao = (
  numero: string,
  liberada: boolean,
  quando: string | null = null,
): VersaoListada => ({
  numero,
  liberada,
  atualizada_em: quando,
  verificacao:
    quando === null
      ? null
      : {
          verificado_em: quando,
          verde: true,
          presentes: PRESENTES,
          faltantes: 0,
          conflitantes: 0,
          suspeitos: 0,
          sem_commits: 0,
        },
});

it("emAberto tira as liberadas", () => {
  expect(
    emAberto([versao(LIBERADA, true), versao(ABERTA, false)]).map((v) => v.numero),
  ).toEqual([ABERTA]);
});

it("sem o fetch, valem as gravadas", () => {
  const gravadas = [versao(ABERTA, false, ANTES)];
  expect(juntarVersoes(gravadas, undefined)).toEqual(gravadas);
});

it("o fetch decide quais versões existem e se estão liberadas", () => {
  const gravadas = [versao(ABERTA, false), versao(LIBERADA, false)];
  const comFetch = [versao(ABERTA, true), versao(SO_NO_FETCH, false)];
  expect(
    juntarVersoes(gravadas, comFetch)?.map((v) => [v.numero, v.liberada]),
  ).toEqual([
    [ABERTA, true],
    [SO_NO_FETCH, false],
  ]);
});

it("verificação e atualização vêm da gravada, mais nova que o fetch", () => {
  const juntas = juntarVersoes([versao(ABERTA, false, DEPOIS)], [versao(ABERTA, false, ANTES)]);
  expect(juntas?.[0]?.atualizada_em).toBe(DEPOIS);
  expect(juntas?.[0]?.verificacao?.verificado_em).toBe(DEPOIS);
});
