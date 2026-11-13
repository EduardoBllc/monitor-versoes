import { describe, expect, it } from "vitest";
import { AcaoAlteracao, Escopo, TipoCampo } from "./api/enums";
import type { ConfigEditavel } from "./api/tipos";
import {
  ORIGEM_MOTOR,
  EstadoSegredo,
  alteracoesDe,
  chaveDe,
  estadoSegredo,
  linhasDe,
  opcoesDe,
  textoDe,
  type Formulario,
} from "./config";

const TABELA_AMBIENTE = "ambiente";
const TABELA_VERSAO = "versao";
const CHAVE_ESQUEMA = "esquema";
const CHAVE_CAMINHO = "caminho";
const CHAVE_SENHA = "BITBUCKET_TOKEN";
const REPO_NOVO = "novo";
const REPO_VELHO = "velho";

const TABELA_TAREFAS = "tarefas";
const TABELA_BRANCHES = "branches";
const CHAVE_PRINCIPAL = "principal";
const PRINCIPAL_REPO = "trunk";
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
      origem: ORIGEM_MOTOR,
      descricao: "",
      exemplo: "",
    },
    {
      escopo: Escopo.AMBIENTE,
      tabela: TABELA_AMBIENTE,
      chave: CHAVE_SENHA,
      tipo: TipoCampo.TEXTO,
      rotulo: "Senha",
      segredo: true,
      opcoes: [],
      origem: ORIGEM_MOTOR,
      descricao: "",
      exemplo: "",
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

  it("valor não editável (lista) nunca vira REMOVER", () => {
    const lista = chaveDe(null, TABELA_TAREFAS, "lista");
    const o: ConfigEditavel = {
      ...original,
      valores: [
        ...original.valores,
        { repo: null, tabela: TABELA_TAREFAS, chave: "lista", valor: null, definido: true, editavel: false },
      ],
    };
    expect(alteracoesDe(o, formulario({ valores: { [lista]: null } }))).toEqual([]);
  });

  it("apagar segredo não definido não gera nada", () => {
    const o: ConfigEditavel = {
      ...original,
      valores: original.valores.map((v) => (v.chave === CHAVE_SENHA ? { ...v, definido: false } : v)),
    };
    expect(alteracoesDe(o, formulario({ valores: { [senha]: null } }))).toEqual([]);
  });

  it("chave livre booleana e inteira mantêm o tipo", () => {
    const flag = chaveDe(null, TABELA_TAREFAS, "flag");
    const n = chaveDe(null, TABELA_TAREFAS, "n");
    const o: ConfigEditavel = {
      ...original,
      valores: [
        ...original.valores,
        { repo: null, tabela: TABELA_TAREFAS, chave: "flag", valor: false, definido: true, editavel: true },
        { repo: null, tabela: TABELA_TAREFAS, chave: "n", valor: 1, definido: true, editavel: true },
      ],
    };
    const r = alteracoesDe(o, formulario({ valores: { [flag]: true, [n]: 2 } }));
    expect(r.map((a) => a.valor)).toEqual([true, 2]);
  });
});

describe("estadoSegredo", () => {
  it("não tocado mostra definido ou não definido; null marca apagar", () => {
    expect(estadoSegredo(undefined, true)).toBe(EstadoSegredo.DEFINIDO);
    expect(estadoSegredo("", false)).toBe(EstadoSegredo.NAO_DEFINIDO);
    expect(estadoSegredo(null, true)).toBe(EstadoSegredo.APAGAR);
  });
});

describe("repo sobrescreve chave do topo", () => {
  it("repo mostra os campos gerais declarados, mesmo sem override no arquivo", () => {
    const linhas = linhasDe(original, REPO_VELHO);
    expect(linhas).toContainEqual(
      expect.objectContaining({ repo: REPO_VELHO, tabela: TABELA_VERSAO, chave: CHAVE_ESQUEMA }),
    );
    expect(linhas.some((l) => l.tabela === TABELA_AMBIENTE)).toBe(false);
  });

  it("repo novo com override de [branches]: CRIAR_REPO e depois DEFINIR no repo", () => {
    const f = formulario({
      reposCriados: [REPO_NOVO],
      valores: { [chaveDe(REPO_NOVO, TABELA_BRANCHES, CHAVE_PRINCIPAL)]: PRINCIPAL_REPO },
    });
    expect(alteracoesDe(original, f)).toEqual([
      { acao: AcaoAlteracao.CRIAR_REPO, repo: REPO_NOVO },
      {
        acao: AcaoAlteracao.DEFINIR,
        repo: REPO_NOVO,
        tabela: TABELA_BRANCHES,
        chave: CHAVE_PRINCIPAL,
        valor: PRINCIPAL_REPO,
      },
    ]);
  });
});

describe("opcoesDe", () => {
  const campo = original.campos[0]!;
  const OPCAO = "semver";
  const FORA = "pacote:Classe";

  it("inclui o valor atual que não está nas opções", () => {
    const comOpcao = { ...campo, opcoes: [OPCAO] };
    expect(opcoesDe(comOpcao, FORA)).toEqual([OPCAO, FORA]);
    expect(opcoesDe(comOpcao, OPCAO)).toEqual([OPCAO]);
    expect(opcoesDe(comOpcao, null)).toEqual([OPCAO]);
  });
});

describe("textoDe", () => {
  const PORTA = "5433";

  it("inteiro gravado como texto aparece como está", () => {
    expect(textoDe(PORTA)).toBe(PORTA);
    expect(textoDe(Number(PORTA))).toBe(PORTA);
    expect(textoDe(null)).toBe("");
  });
});
