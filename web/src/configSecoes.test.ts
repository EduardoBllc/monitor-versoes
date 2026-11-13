import { afterEach, describe, expect, it, vi } from "vitest";
import {
  Chave,
  Escopo,
  EstadoTeste,
  GrupoPlugin,
  Tabela,
  TipoCampo,
  VarAmbiente,
} from "./api/enums";
import type { Campo, ConfigEditavel, ResultadoTeste, ValorLido } from "./api/tipos";
import { TABELA_AMBIENTE } from "./apoioTeste";
import {
  ORIGEM_MOTOR,
  alteracoesDe,
  chaveDe,
  type Formulario,
  type Linha,
} from "./config";
import {
  CHAVE_CAMINHO,
  GrupoLateral,
  Marca,
  Secao,
  assinatura,
  gravarPulados,
  lerPulados,
  linhasDaSecao,
  linhasDoRepo,
  marcaDe,
  pendencias,
} from "./configSecoes";

const TICKIO = "tickio";
const JIRA = "jira";
const BITBUCKET = "bitbucket";
const SEMVER = "semver";
const CALVER = "calver";
const PROPORCIONAL = "proporcional";
const MODULO = "meu.modulo:Fonte";
const REPO = "app";

const TABELA_TICKIO = "tickio";
const TABELA_JIRA = "jira";
const TABELA_SEMVER = "semver";
const TABELA_MINHA = "minha";
const TABELA_LIVRE = "extra";
const URL = "url";
const PROJETO = "projeto";
const PREFIXO = "prefixo";
const LIVRE = "coisa";
const TICKIO_TOKEN = "TICKIO_TOKEN";
const JIRA_TOKEN = "JIRA_TOKEN";
const BITBUCKET_EMAIL = "BITBUCKET_EMAIL";
const BITBUCKET_TOKEN = "BITBUCKET_TOKEN";

function campo(
  escopo: Escopo,
  tabela: string | null,
  chave: string,
  extra: Partial<Campo> = {},
): Campo {
  return {
    escopo,
    tabela,
    chave,
    tipo: TipoCampo.TEXTO,
    rotulo: chave,
    segredo: false,
    opcoes: [],
    origem: ORIGEM_MOTOR,
    descricao: "",
    exemplo: "",
    ...extra,
  };
}

const plugin = (grupo: GrupoPlugin, origem: string) => ({ grupo, origem });
const segredo = { segredo: true };

const CAMPOS: Campo[] = [
  campo(Escopo.GERAL, Tabela.VERSAO, Chave.ESQUEMA, { padrao: SEMVER }),
  campo(Escopo.GERAL, Tabela.VERSAO, Chave.ATRIBUICAO, { padrao: PROPORCIONAL }),
  campo(Escopo.GERAL, Tabela.BRANCHES, Chave.PRINCIPAL),
  campo(Escopo.GERAL, Tabela.TAREFAS, Chave.FONTE),
  campo(Escopo.GERAL, Tabela.PRS, Chave.FONTE),
  campo(Escopo.REPO, null, CHAVE_CAMINHO),
  campo(Escopo.REPO, Tabela.VERSAO, Chave.PISO),
  campo(Escopo.AMBIENTE, TABELA_AMBIENTE, VarAmbiente.DATABASE_SQLITE_PATH),
  campo(Escopo.GERAL, TABELA_TICKIO, URL, plugin(GrupoPlugin.TAREFAS, TICKIO)),
  campo(Escopo.REPO, TABELA_TICKIO, PROJETO, plugin(GrupoPlugin.TAREFAS, TICKIO)),
  campo(Escopo.AMBIENTE, TABELA_AMBIENTE, TICKIO_TOKEN, {
    ...plugin(GrupoPlugin.TAREFAS, TICKIO),
    ...segredo,
  }),
  campo(Escopo.GERAL, TABELA_JIRA, URL, plugin(GrupoPlugin.TAREFAS, JIRA)),
  campo(Escopo.REPO, TABELA_JIRA, PROJETO, plugin(GrupoPlugin.TAREFAS, JIRA)),
  campo(Escopo.AMBIENTE, TABELA_AMBIENTE, JIRA_TOKEN, {
    ...plugin(GrupoPlugin.TAREFAS, JIRA),
    ...segredo,
  }),
  campo(Escopo.GERAL, TABELA_MINHA, URL, plugin(GrupoPlugin.TAREFAS, MODULO)),
  campo(Escopo.AMBIENTE, TABELA_AMBIENTE, BITBUCKET_EMAIL, plugin(GrupoPlugin.PRS, BITBUCKET)),
  campo(Escopo.AMBIENTE, TABELA_AMBIENTE, BITBUCKET_TOKEN, {
    ...plugin(GrupoPlugin.PRS, BITBUCKET),
    ...segredo,
  }),
  campo(Escopo.GERAL, TABELA_SEMVER, PREFIXO, plugin(GrupoPlugin.ESQUEMAS, SEMVER)),
];

const lido = (
  repo: string | null,
  tabela: string | null,
  chave: string,
  valor: ValorLido["valor"],
): ValorLido => ({ repo, tabela, chave, valor, definido: true, editavel: true });

const CONFIG: ConfigEditavel = {
  versao: "v1",
  repos: [REPO],
  campos: CAMPOS,
  valores: [
    lido(null, Tabela.TAREFAS, Chave.FONTE, TICKIO),
    lido(null, TABELA_AMBIENTE, TICKIO_TOKEN, null),
    lido(null, TABELA_JIRA, URL, "https://jira"),
    lido(null, TABELA_LIVRE, LIVRE, "x"),
    lido(REPO, null, CHAVE_CAMINHO, "/app"),
    lido(REPO, Tabela.BRANCHES, Chave.PRINCIPAL, "trunk"),
  ],
};

const fonteTarefas = chaveDe(null, Tabela.TAREFAS, Chave.FONTE);
const fontePrs = chaveDe(null, Tabela.PRS, Chave.FONTE);
const esquema = chaveDe(null, Tabela.VERSAO, Chave.ESQUEMA);
const tickioUrl = chaveDe(null, TABELA_TICKIO, URL);
const caminho = chaveDe(REPO, null, CHAVE_CAMINHO);
const principalRepo = chaveDe(REPO, Tabela.BRANCHES, Chave.PRINCIPAL);

// Como a modal monta: valores lidos, menos os segredos.
function formulario(valores: Formulario["valores"] = {}): Formulario {
  return {
    valores: {
      [fonteTarefas]: TICKIO,
      [chaveDe(null, TABELA_JIRA, URL)]: "https://jira",
      [chaveDe(null, TABELA_LIVRE, LIVRE)]: "x",
      [caminho]: "/app",
      [principalRepo]: "trunk",
      ...valores,
    },
    reposCriados: [],
    reposRemovidos: [],
  };
}

const chaves = (linhas: Linha[]) => linhas.map((l) => chaveDe(l.repo, l.tabela, l.chave));
const ambiente = (chave: string) => chaveDe(null, TABELA_AMBIENTE, chave);

describe("linhasDaSecao", () => {
  it("campos do plugin escolhido vão para Fonte de tarefas, inclusive os do ambiente", () => {
    expect(chaves(linhasDaSecao(CONFIG, formulario(), Secao.TAREFAS))).toEqual([
      fonteTarefas,
      tickioUrl,
      ambiente(TICKIO_TOKEN),
    ]);
  });

  it("trocar a fonte no formulário troca os campos, sem salvar", () => {
    const tarefas = chaves(linhasDaSecao(CONFIG, formulario({ [fonteTarefas]: JIRA }), Secao.TAREFAS));
    expect(tarefas).toContain(ambiente(JIRA_TOKEN));
    expect(tarefas).not.toContain(ambiente(TICKIO_TOKEN));
  });

  it("campos do host de PR escolhido vão para Fonte de PR", () => {
    expect(chaves(linhasDaSecao(CONFIG, formulario({ [fontePrs]: BITBUCKET }), Secao.PRS))).toEqual([
      fontePrs,
      ambiente(BITBUCKET_EMAIL),
      ambiente(BITBUCKET_TOKEN),
    ]);
  });

  it("campo de plugin de esquema vai para Versões, seguindo o padrão quando vazio", () => {
    const prefixo = chaveDe(null, TABELA_SEMVER, PREFIXO);
    expect(chaves(linhasDaSecao(CONFIG, formulario(), Secao.VERSOES))).toContain(prefixo);
    const calver = formulario({ [esquema]: CALVER });
    expect(chaves(linhasDaSecao(CONFIG, calver, Secao.VERSOES))).not.toContain(prefixo);
  });

  it("plugin escolhido por modulo:Classe leva os campos para a seção do grupo", () => {
    const f = formulario({ [fonteTarefas]: MODULO });
    const minha = chaveDe(null, TABELA_MINHA, URL);
    expect(chaves(linhasDaSecao(CONFIG, f, Secao.TAREFAS))).toContain(minha);
    expect(chaves(linhasDaSecao(CONFIG, f, Secao.AVANCADO))).not.toContain(minha);
  });

  it("chave livre e campo com valor de plugin não escolhido caem em Avançado", () => {
    expect(chaves(linhasDaSecao(CONFIG, formulario(), Secao.AVANCADO))).toEqual([
      ambiente(VarAmbiente.DATABASE_SQLITE_PATH),
      chaveDe(null, TABELA_JIRA, URL),
      chaveDe(null, TABELA_LIVRE, LIVRE),
    ]);
  });

  it("plugin não escolhido e sem valor não aparece em seção nenhuma", () => {
    const todas = Object.values(Secao).flatMap((s) => chaves(linhasDaSecao(CONFIG, formulario(), s)));
    expect(todas).not.toContain(ambiente(JIRA_TOKEN));
    expect(todas).not.toContain(chaveDe(null, TABELA_MINHA, URL));
  });

  it("plugin escolhido só por um repo leva o [ambiente] dele para a seção do grupo", () => {
    const f = formulario({
      [chaveDe(REPO, Tabela.TAREFAS, Chave.FONTE)]: JIRA,
      [chaveDe(REPO, Tabela.PRS, Chave.FONTE)]: BITBUCKET,
    });
    expect(chaves(linhasDaSecao(CONFIG, f, Secao.TAREFAS))).toContain(ambiente(JIRA_TOKEN));
    expect(chaves(linhasDaSecao(CONFIG, f, Secao.PRS))).toContain(ambiente(BITBUCKET_TOKEN));
    const proprias = chaves(linhasDoRepo(CONFIG, f, REPO).proprias);
    expect(proprias).toContain(chaveDe(REPO, TABELA_JIRA, PROJETO));
    expect(proprias).not.toContain(chaveDe(REPO, TABELA_TICKIO, PROJETO));
  });

  it("campo de plugin não escolhido com valor no arquivo continua em Avançado ao ser limpo", () => {
    const jiraUrl = chaveDe(null, TABELA_JIRA, URL);
    expect(chaves(linhasDaSecao(CONFIG, formulario({ [jiraUrl]: "" }), Secao.AVANCADO))).toContain(jiraUrl);
  });

  it("nenhuma linha aparece em duas seções", () => {
    const porRepo = formulario({ [chaveDe(REPO, Tabela.TAREFAS, Chave.FONTE)]: JIRA });
    for (const f of [formulario(), formulario({ [fonteTarefas]: JIRA, [fontePrs]: BITBUCKET }), porRepo]) {
      const todas = Object.values(Secao).flatMap((s) => chaves(linhasDaSecao(CONFIG, f, s)));
      expect(new Set(todas).size).toBe(todas.length);
    }
  });
});

describe("linhasDoRepo", () => {
  it("repo lista só as sobrescritas existentes e remover uma devolve às sobrescrevíveis", () => {
    const antes = linhasDoRepo(CONFIG, formulario(), REPO);
    expect(chaves(antes.proprias)).toEqual([
      caminho,
      chaveDe(REPO, Tabela.VERSAO, Chave.PISO),
      chaveDe(REPO, TABELA_TICKIO, PROJETO),
    ]);
    expect(chaves(antes.sobrescritas)).toEqual([principalRepo]);
    expect(chaves(antes.sobrescreviveis)).toContain(chaveDe(REPO, Tabela.PRS, Chave.FONTE));
    expect(chaves(antes.sobrescreviveis)).not.toContain(chaveDe(REPO, TABELA_JIRA, URL));

    const depois = linhasDoRepo(CONFIG, formulario({ [principalRepo]: null }), REPO);
    expect(depois.sobrescritas).toEqual([]);
    expect(chaves(depois.sobrescreviveis)).toContain(principalRepo);
  });

  it("sobrescrita acrescentada vazia fica no bloco, e limpar não a tira de lá", () => {
    const esquemaRepo = chaveDe(REPO, Tabela.VERSAO, Chave.ESQUEMA);
    const acrescentada = formulario({ [esquemaRepo]: "" });
    expect(chaves(linhasDoRepo(CONFIG, acrescentada, REPO).sobrescritas)).toContain(esquemaRepo);
    expect(alteracoesDe(CONFIG, acrescentada)).toEqual(alteracoesDe(CONFIG, formulario()));

    const limpa = linhasDoRepo(CONFIG, formulario({ [principalRepo]: "" }), REPO);
    expect(chaves(limpa.sobrescritas)).toContain(principalRepo);
  });

  it("campos do plugin que o repo escolhe ficam sob a sobrescrita, e escolha vazia não leva nenhum", () => {
    const fonteRepo = chaveDe(REPO, Tabela.TAREFAS, Chave.FONTE);
    const comJira = linhasDoRepo(CONFIG, formulario({ [fonteRepo]: JIRA }), REPO).doPlugin;
    expect(chaves(comJira[fonteRepo] ?? [])).toEqual([chaveDe(REPO, TABELA_JIRA, URL)]);

    expect(linhasDoRepo(CONFIG, formulario({ [fonteRepo]: "" }), REPO).doPlugin).toEqual({});
  });
});

const VAZIA: ConfigEditavel = { versao: "v1", repos: [], campos: CAMPOS, valores: [] };
const semNada: Formulario = { valores: {}, reposCriados: [], reposRemovidos: [] };
const falha: ResultadoTeste = { estado: EstadoTeste.FALHA, detalhe: "", correcao: "" };

describe("pendencias", () => {
  it("config vazia: três segmentos pendentes e a próxima é Adicionar repo", () => {
    const p = pendencias(VAZIA, semNada, {}, new Set());
    expect(p.segmentos).toEqual([
      { nome: GrupoLateral.REPOSITORIOS, destino: Secao.NOVO_REPO, marca: Marca.PENDENTE },
      { nome: expect.any(String), destino: Secao.PRS, marca: Marca.PENDENTE },
      { nome: expect.any(String), destino: Secao.TAREFAS, marca: Marca.PENDENTE },
    ]);
    expect(p.proxima).toBe(Secao.NOVO_REPO);
    expect(p.completa).toBe(false);
  });

  it("pular conta como pronta e a barra completa", () => {
    const f = formulario({ [fonteTarefas]: "" });
    expect(pendencias(CONFIG, f, {}, new Set()).proxima).toBe(Secao.PRS);
    const p = pendencias(CONFIG, f, {}, new Set([Secao.PRS, Secao.TAREFAS]));
    expect(p.segmentos.map((s) => s.marca)).toEqual([Marca.PRONTA, Marca.PRONTA, Marca.PRONTA]);
    expect(p.proxima).toBeNull();
    expect(p.completa).toBe(true);
  });

  it("teste com falha vigente marca FALHOU; mudar campo da seção invalida", () => {
    const f = formulario();
    const testes = { [assinatura(Secao.TAREFAS, CONFIG, f)]: falha };
    expect(marcaDe(Secao.TAREFAS, CONFIG, f, testes, new Set())).toBe(Marca.FALHOU);
    const mudado = formulario({ [tickioUrl]: "https://outro" });
    expect(marcaDe(Secao.TAREFAS, CONFIG, mudado, testes, new Set())).toBe(Marca.PRONTA);
    const tokenApagado = formulario({ [ambiente(TICKIO_TOKEN)]: null });
    expect(marcaDe(Secao.TAREFAS, CONFIG, tokenApagado, testes, new Set())).toBe(Marca.PRONTA);

    const semCaminho = formulario({ [caminho]: "" });
    const doRepo = { [assinatura({ repo: REPO }, CONFIG, semCaminho)]: falha };
    const repos = pendencias(CONFIG, semCaminho, doRepo, new Set()).segmentos[0];
    expect(repos).toEqual({
      nome: GrupoLateral.REPOSITORIOS,
      destino: { repo: REPO },
      marca: Marca.FALHOU,
    });
  });
});

describe("pulados", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("o pulo sobrevive a reabrir no mesmo navegador", () => {
    const guardado = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => guardado.get(k) ?? null,
      setItem: (k: string, v: string) => guardado.set(k, v),
    });
    gravarPulados(new Set([Secao.PRS]));
    expect(lerPulados()).toEqual(new Set([Secao.PRS]));
  });

  it("localStorage que lança não quebra e nada fica pulado", () => {
    vi.stubGlobal(
      "localStorage",
      new Proxy(
        {},
        {
          get() {
            throw new Error("bloqueado");
          },
        },
      ),
    );
    expect(() => gravarPulados(new Set([Secao.PRS]))).not.toThrow();
    expect(lerPulados()).toEqual(new Set());
  });
});
