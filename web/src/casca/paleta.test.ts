import { expect, it } from "vitest";
import type { VersaoListada } from "../api/tipos";
import { Pagina } from "../rotas";
import { TipoAcao, acoesDaPaleta } from "./paleta";

const REPO = "app";
const VERSAO = "1.2.0";
const CHAMADO = "123";

it("acoesDaPaleta gera repo, versão e chamado com a rota certa", () => {
  const versoes = { [REPO]: [{ numero: VERSAO } as VersaoListada] };
  const acoes = acoesDaPaleta(
    [{ nome: REPO, caminho: null }],
    versoes,
    [{ repo: REPO, versao: VERSAO, chamado: CHAMADO }],
  );
  const rotaVersao = { pagina: Pagina.VERSAO, repo: REPO, versao: VERSAO };
  expect(acoes.map((a) => [a.tipo, a.rota])).toEqual([
    [TipoAcao.REPO, { pagina: Pagina.REPO, repo: REPO }],
    [TipoAcao.VERSAO, rotaVersao],
    [TipoAcao.CHAMADO, rotaVersao],
  ]);
  expect(acoes[2]?.rotulo).toContain(CHAMADO);
});
