import { expect, it } from "vitest";
import type { VersaoListada } from "./api/tipos";
import { emAberto } from "./versoes";

const ABERTA = "1.1.0";
const LIBERADA = "1.0.0";

const versao = (numero: string, liberada: boolean): VersaoListada => ({
  numero,
  liberada,
  atualizada_em: null,
  verificacao: null,
});

it("emAberto tira as liberadas", () => {
  expect(
    emAberto([versao(LIBERADA, true), versao(ABERTA, false)]).map((v) => v.numero),
  ).toEqual([ABERTA]);
});
