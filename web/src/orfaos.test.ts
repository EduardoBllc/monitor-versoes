import { expect, it } from "vitest";
import type { OrfaoDaVersao } from "./api/tipos";
import { caminhoJulgamento, caminhoOrfaos, rotuloJulgamento } from "./orfaos";

const orfao = (julgamento: OrfaoDaVersao["julgamento"]): OrfaoDaVersao => ({
  hash_origem: "aaaa1111",
  assunto: "assunto",
  data: "2026-01-02T00:00:00Z",
  julgamento,
});

it("rótulo do julgamento nos três casos", () => {
  expect(rotuloJulgamento(orfao(null))).toBe("pendente");
  expect(
    rotuloJulgamento(
      orfao({
        hash_origem: "aaaa1111",
        versao_numero: "1.0.0",
        chamado: "123",
        motivo: "m",
      }),
    ),
  ).toBe("pertence a 123");
  expect(
    rotuloJulgamento(
      orfao({
        hash_origem: "aaaa1111",
        versao_numero: "1.0.0",
        chamado: null,
        motivo: "m",
      }),
    ),
  ).toBe("nenhum");
});

it("caminhos escapam repo, versão e hash", () => {
  expect(caminhoOrfaos("a b", "1/2")).toBe("/api/repos/a%20b/versoes/1%2F2/orfaos");
  expect(caminhoJulgamento("a b", "1/2", "ab#c")).toBe(
    "/api/repos/a%20b/versoes/1%2F2/orfaos/ab%23c/julgamento",
  );
});
