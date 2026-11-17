import { expect, it } from "vitest";
import { Pagina, caminhoDa, lerRota, type Rota } from "./rotas";

const REPO = "meu-repo";
const VERSAO = "14.0.0";

it.each<Rota>([
  { pagina: Pagina.INICIO },
  { pagina: Pagina.CONFIG },
  { pagina: Pagina.REPO, repo: REPO },
  { pagina: Pagina.VERSAO, repo: REPO, versao: VERSAO },
])("ida e volta de $pagina", (rota) => {
  const caminho = caminhoDa(rota);
  expect(lerRota(caminho)).toEqual(rota);
  expect(caminhoDa(lerRota(caminho))).toBe(caminho);
});

it("codifica barra e espaço no nome", () => {
  const rota: Rota = { pagina: Pagina.VERSAO, repo: "a b", versao: "1/2" };
  expect(caminhoDa(rota)).toBe("/r/a%20b/v/1%2F2");
  expect(lerRota(caminhoDa(rota))).toEqual(rota);
});

it("caminho desconhecido abre o início", () => {
  expect(lerRota("/qualquer/coisa")).toEqual({ pagina: Pagina.INICIO });
});
