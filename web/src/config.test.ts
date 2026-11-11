import { describe, expect, it } from "vitest";
import { AcaoAlteracao, Escopo, TipoCampo } from "./api/enums";
import type { ConfigEditavel } from "./api/tipos";
import { alteracoesDe, chaveDe, type Formulario } from "./config";

const TABELA_VERSAO = "versao";
const TABELA_AMBIENTE = "ambiente";
const CHAVE_ESQUEMA = "esquema";
const CHAVE_CAMINHO = "caminho";
const CHAVE_SENHA = "DATABASE_PASSWORD";
const REPO_NOVO = "novo";
const REPO_VELHO = "velho";

const original: ConfigEditavel = {
  versao: "v1",
  repos: [REPO_VELHO],
  campos: [
    {
      escopo: Escopo.GERAL,
      tabela: TABELA_VERSAO,
      chave: CHAVE_ESQUEMA,
      tipo: TipoCampo.TEXTO,
      rotulo: "Esquema",
      segredo: false,
      opcoes: [],
      origem: "motor",
    },
    {
      escopo: Escopo.AMBIENTE,
      tabela: TABELA_AMBIENTE,
      chave: CHAVE_SENHA,
      tipo: TipoCampo.TEXTO,
      rotulo: "Senha",
      segredo: true,
      opcoes: [],
      origem: "motor",
    },
  ],
  valores: [
    { repo: null, tabela: TABELA_VERSAO, chave: CHAVE_ESQUEMA, valor: "semver", definido: true, editavel: true },
    { repo: null, tabela: TABELA_AMBIENTE, chave: CHAVE_SENHA, valor: null, definido: true, editavel: true },
    { repo: REPO_VELHO, tabela: null, chave: CHAVE_CAMINHO, valor: "/x", definido: true, editavel: true },
  ],
};

const esquema = chaveDe(null, TABELA_VERSAO, CHAVE_ESQUEMA);
const senha = chaveDe(null, TABELA_AMBIENTE, CHAVE_SENHA);

function formulario(parcial: Partial<Formulario> = {}): Formulario {
  return {
    valores: { [esquema]: "semver", [chaveDe(REPO_VELHO, null, CHAVE_CAMINHO)]: "/x" },
    reposCriados: [],
    reposRemovidos: [],
    ...parcial,
  };
}

describe("alteracoesDe", () => {
  it("sem mudança não gera alteração", () => {
    expect(alteracoesDe(original, formulario())).toEqual([]);
  });

  it("valor alterado gera um DEFINIR", () => {
    const f = formulario({ valores: { [esquema]: "calver" } });
    expect(alteracoesDe(original, f)).toEqual([
      { acao: AcaoAlteracao.DEFINIR, repo: null, tabela: TABELA_VERSAO, chave: CHAVE_ESQUEMA, valor: "calver" },
    ]);
  });

  it("campo esvaziado gera REMOVER", () => {
    const f = formulario({ valores: { [esquema]: "" } });
    expect(alteracoesDe(original, f)).toEqual([
      { acao: AcaoAlteracao.REMOVER, repo: null, tabela: TABELA_VERSAO, chave: CHAVE_ESQUEMA },
    ]);
  });

  it("repo criado vem antes das DEFINIR dele", () => {
    const f = formulario({
      reposCriados: [REPO_NOVO],
      valores: { [chaveDe(REPO_NOVO, null, CHAVE_CAMINHO)]: "/n", [esquema]: "calver" },
    });
    const acoes = alteracoesDe(original, f).map((a) => [a.acao, a.repo ?? null]);
    expect(acoes[0]).toEqual([AcaoAlteracao.CRIAR_REPO, REPO_NOVO]);
    expect(acoes).toContainEqual([AcaoAlteracao.DEFINIR, REPO_NOVO]);
  });

  it("repo removido gera só REMOVER_REPO", () => {
    const f = formulario({
      reposRemovidos: [REPO_VELHO],
      valores: { [chaveDe(REPO_VELHO, null, CHAVE_CAMINHO)]: "/outro" },
    });
    expect(alteracoesDe(original, f)).toEqual([
      { acao: AcaoAlteracao.REMOVER_REPO, repo: REPO_VELHO },
    ]);
  });

  it("segredo não tocado não gera nada, digitado define, apagado remove", () => {
    expect(alteracoesDe(original, formulario({ valores: { [senha]: "" } }))).toEqual([]);
    const definir = alteracoesDe(original, formulario({ valores: { [senha]: "s3" } }));
    expect(definir[0]?.acao).toBe(AcaoAlteracao.DEFINIR);
    const apagar = alteracoesDe(original, formulario({ valores: { [senha]: null } }));
    expect(apagar[0]?.acao).toBe(AcaoAlteracao.REMOVER);
  });
});
