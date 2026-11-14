import { Chave, Escopo, EstadoTeste, GrupoPlugin, Tabela } from "./api/enums";
import type { ConfigEditavel, ResultadoTeste } from "./api/tipos";
import { achaCampo, alteracoesDe, chaveDe, linhasDe, vazio, type Formulario, type Linha } from "./config";

export const CHAVE_CAMINHO = "caminho";
export const CHAVE_PULADOS = "monitor-versoes:config:pulados";

export enum Secao {
  PRS = "prs",
  TAREFAS = "tarefas",
  VERSOES = "versoes",
  NOVO_REPO = "novo-repo",
  AVANCADO = "avancado",
}

export type Destino = Secao | { repo: string };

export enum GrupoLateral {
  CONEXOES = "Conexões",
  COMO_TRABALHA = "Como você trabalha",
  REPOSITORIOS = "Repositórios",
  AVANCADO = "Avançado",
}

// Os itens de repo entram no grupo Repositórios antes de NOVO_REPO.
export const LATERAL: { grupo: GrupoLateral; secoes: Secao[] }[] = [
  { grupo: GrupoLateral.CONEXOES, secoes: [Secao.PRS, Secao.TAREFAS] },
  { grupo: GrupoLateral.COMO_TRABALHA, secoes: [Secao.VERSOES] },
  { grupo: GrupoLateral.REPOSITORIOS, secoes: [Secao.NOVO_REPO] },
  { grupo: GrupoLateral.AVANCADO, secoes: [Secao.AVANCADO] },
];

export const NOME_SECAO: Record<Secao, string> = {
  [Secao.PRS]: "Fonte de PR",
  [Secao.TAREFAS]: "Fonte de tarefas",
  [Secao.VERSOES]: "Versões e branches",
  [Secao.NOVO_REPO]: "+ Adicionar repo",
  [Secao.AVANCADO]: "Avançado",
};

type TabelaChave = [string, string];

const ESCOLHE: Record<GrupoPlugin, TabelaChave> = {
  [GrupoPlugin.TAREFAS]: [Tabela.TAREFAS, Chave.FONTE],
  [GrupoPlugin.PRS]: [Tabela.PRS, Chave.FONTE],
  [GrupoPlugin.ESQUEMAS]: [Tabela.VERSAO, Chave.ESQUEMA],
  [GrupoPlugin.ATRIBUICOES]: [Tabela.VERSAO, Chave.ATRIBUICAO],
  [GrupoPlugin.SUGESTAO]: [Tabela.SUGESTAO, Chave.PROVEDOR],
};

export const SECAO_DO_GRUPO: Record<GrupoPlugin, Secao> = {
  [GrupoPlugin.TAREFAS]: Secao.TAREFAS,
  [GrupoPlugin.PRS]: Secao.PRS,
  [GrupoPlugin.ESQUEMAS]: Secao.VERSOES,
  [GrupoPlugin.ATRIBUICOES]: Secao.VERSOES,
  // Configurar a sugestão pela interface está fora do escopo da #174: o que existe vai para Avançado.
  [GrupoPlugin.SUGESTAO]: Secao.AVANCADO,
};

// Campo do motor fora deste mapa vai para Avançado.
const CAMPOS_DO_MOTOR: Partial<Record<Secao, TabelaChave[]>> = {
  [Secao.PRS]: [ESCOLHE[GrupoPlugin.PRS]],
  [Secao.TAREFAS]: [ESCOLHE[GrupoPlugin.TAREFAS]],
  [Secao.VERSOES]: [
    ESCOLHE[GrupoPlugin.ESQUEMAS],
    ESCOLHE[GrupoPlugin.ATRIBUICOES],
    [Tabela.LIBERACAO, Chave.TAG],
    [Tabela.BRANCHES, Chave.VERSAO],
    [Tabela.BRANCHES, Chave.PRINCIPAL],
    [Tabela.REFERENCIA, Chave.PADRAO],
  ],
};

// Ordem da barra de progresso, depois de Repositórios.
const COBRADAS: Partial<Record<Secao, GrupoPlugin>> = {
  [Secao.PRS]: GrupoPlugin.PRS,
  [Secao.TAREFAS]: GrupoPlugin.TAREFAS,
};

const textoNo = (f: Formulario, repo: string | null, [tabela, chave]: TabelaChave): string => {
  const v = f.valores[chaveDe(repo, tabela, chave)];
  return vazio(v) ? "" : String(v);
};

/** Valor que escolhe o plugin do grupo: o do repo, senão o do topo, senão o padrão. */
export function escolhido(
  config: ConfigEditavel,
  formulario: Formulario,
  grupo: GrupoPlugin,
  repo: string | null,
): string {
  const tc = ESCOLHE[grupo];
  return (
    (repo === null ? "" : textoNo(formulario, repo, tc)) ||
    textoNo(formulario, null, tc) ||
    (achaCampo(config.campos, null, ...tc)?.padrao ?? "")
  );
}

const reposAtivos = (config: ConfigEditavel, f: Formulario): string[] =>
  [...config.repos, ...f.reposCriados].filter((r) => !f.reposRemovidos.includes(r));

// Valor no arquivo ou chave no formulário (null = marcada para remover, "" = acabou de entrar).
function temValor(l: Linha, f: Formulario): boolean {
  const v = f.valores[chaveDe(l.repo, l.tabela, l.chave)];
  return l.lido?.definido === true || (v !== undefined && v !== null);
}

// Ausente do formulário só acontece com segredo ou valor não escalar: vale o arquivo.
function sobrescreve(l: Linha, f: Formulario): boolean {
  const v = f.valores[chaveDe(l.repo, l.tabela, l.chave)];
  return v === undefined ? l.lido?.definido === true : v !== null;
}

// O tipo gerado é a união dos valores; o enum espelha os mesmos.
const grupoDe = (l: Linha) => (l.campo?.grupo ?? undefined) as GrupoPlugin | undefined;

// No topo, vale também o plugin que só um repo escolhe: o [ambiente] dele mora no topo.
function doEscolhido(config: ConfigEditavel, f: Formulario, l: Linha, grupo: GrupoPlugin): boolean {
  const repos = l.repo === null ? [null, ...reposAtivos(config, f)] : [l.repo];
  return repos.some((r) => l.campo?.origem === escolhido(config, f, grupo, r));
}

// Campo de plugin não escolhido só aparece se ainda tem valor.
function visivel(config: ConfigEditavel, f: Formulario, l: Linha): boolean {
  const grupo = grupoDe(l);
  return grupo === undefined || doEscolhido(config, f, l, grupo) || temValor(l, f);
}

function secaoDe(config: ConfigEditavel, f: Formulario, l: Linha): Secao | null {
  if (!visivel(config, f, l)) return null;
  const grupo = grupoDe(l);
  if (grupo !== undefined && doEscolhido(config, f, l, grupo)) return SECAO_DO_GRUPO[grupo];
  const achada = Object.entries(CAMPOS_DO_MOTOR).find(([, tcs]) =>
    tcs.some(([t, c]) => t === l.tabela && c === l.chave),
  );
  return achada ? (achada[0] as Secao) : Secao.AVANCADO;
}

/** Linhas do topo que moram na seção, segundo o formulário. */
export function linhasDaSecao(config: ConfigEditavel, formulario: Formulario, secao: Secao): Linha[] {
  return linhasDe(config, null).filter((l) => secaoDe(config, formulario, l) === secao);
}

const grupoEscolhidoPor = (l: Linha): GrupoPlugin | undefined =>
  (Object.keys(ESCOLHE) as GrupoPlugin[]).find((g) => ESCOLHE[g][0] === l.tabela && ESCOLHE[g][1] === l.chave);

/**
 * Linhas de um repo: as dele, as gerais que ele sobrescreve, as que pode sobrescrever e,
 * por chave da sobrescrita que escolhe um plugin, os campos desse plugin.
 */
export function linhasDoRepo(
  config: ConfigEditavel,
  formulario: Formulario,
  repo: string,
): { proprias: Linha[]; sobrescritas: Linha[]; sobrescreviveis: Linha[]; doPlugin: Record<string, Linha[]> } {
  const linhas = linhasDe(config, repo).filter((l) => visivel(config, formulario, l));
  const gerais = linhas.filter((l) => l.campo?.escopo !== Escopo.REPO);
  const sobrescritas = gerais.filter((l) => sobrescreve(l, formulario));
  // Escolha ainda vazia herda o plugin geral: os campos dele não são "deste" repo.
  const doPlugin = sobrescritas.flatMap((escolha): [string, Linha[]][] => {
    const k = chaveDe(escolha.repo, escolha.tabela, escolha.chave);
    const grupo = grupoEscolhidoPor(escolha);
    if (grupo === undefined || vazio(formulario.valores[k])) return [];
    const origem = escolhido(config, formulario, grupo, repo);
    return [[k, gerais.filter((l) => grupoDe(l) === grupo && l.campo?.origem === origem)]];
  });
  return {
    proprias: linhas.filter((l) => l.campo?.escopo === Escopo.REPO),
    sobrescritas,
    sobrescreviveis: gerais.filter((l) => !sobrescreve(l, formulario)),
    doPlugin: Object.fromEntries(doPlugin),
  };
}

export enum Marca {
  PRONTA = "pronta",
  PENDENTE = "pendente",
  FALHOU = "falhou",
  NENHUMA = "nenhuma",
}

// Precisa da config: só o catálogo diz a que seção um campo de plugin pertence.
/** Valores do formulário que pertencem ao destino; o teste só vale com a mesma assinatura. */
export function assinatura(destino: Destino, config: ConfigEditavel, formulario: Formulario): string {
  const chaves =
    typeof destino === "string"
      ? linhasDaSecao(config, formulario, destino).map((l) => chaveDe(l.repo, l.tabela, l.chave))
      : Object.keys(formulario.valores).filter((k) => (JSON.parse(k) as [string | null])[0] === destino.repo);
  // Ausente e "" são "não tocado"; null (apagar segredo) precisa invalidar o teste.
  const valor = (k: string) => (formulario.valores[k] === undefined ? "" : formulario.valores[k]);
  return JSON.stringify([destino, chaves.map((k) => [k, valor(k)])]);
}

/** Chave da recusa (422): ela vale para o rascunho inteiro, não só para os campos da seção. */
export function assinaturaDaRecusa(destino: Destino, config: ConfigEditavel, formulario: Formulario): string {
  return JSON.stringify([assinatura(destino, config, formulario), alteracoesDe(config, formulario)]);
}

/** Guarda o resultado do teste de `formulario`; ele substitui o do outro tipo (OK x recusa) do mesmo formulário. */
export function comTeste(
  testes: Record<string, ResultadoTeste>,
  destino: Destino,
  config: ConfigEditavel,
  formulario: Formulario,
  resultado: ResultadoTeste,
  recusa: boolean,
): Record<string, ResultadoTeste> {
  // A recusa também depende do disco (caminho criado depois): o mais recente é o que vale.
  const daSecao = assinatura(destino, config, formulario);
  const daRecusa = assinaturaDaRecusa(destino, config, formulario);
  const novos = { ...testes, [recusa ? daRecusa : daSecao]: resultado };
  delete novos[recusa ? daSecao : daRecusa];
  return novos;
}

/** Resultado de teste que ainda vale para o destino com o formulário atual. */
export function testeVigente(
  destino: Destino,
  config: ConfigEditavel,
  formulario: Formulario,
  testes: Record<string, ResultadoTeste>,
): ResultadoTeste | undefined {
  // A recusa cobre o rascunho inteiro: se casa, é mais recente que um resultado só da seção.
  return (
    testes[assinaturaDaRecusa(destino, config, formulario)] ?? testes[assinatura(destino, config, formulario)]
  );
}

const temCaminho = (f: Formulario, repo: string): boolean =>
  !vazio(f.valores[chaveDe(repo, null, CHAVE_CAMINHO)]);

/** Marca do destino na lateral; teste com falha vigente vence. */
export function marcaDe(
  destino: Destino,
  config: ConfigEditavel,
  formulario: Formulario,
  testes: Record<string, ResultadoTeste>,
  pulados: Set<Secao>,
): Marca {
  const grupo = typeof destino === "string" ? COBRADAS[destino] : undefined;
  if (typeof destino === "string" && grupo === undefined) return Marca.NENHUMA;
  if (testeVigente(destino, config, formulario, testes)?.estado === EstadoTeste.FALHA) return Marca.FALHOU;
  const pronta =
    typeof destino === "string"
      ? pulados.has(destino) || (grupo !== undefined && escolhido(config, formulario, grupo, null) !== "")
      : temCaminho(formulario, destino.repo);
  return pronta ? Marca.PRONTA : Marca.PENDENTE;
}

export interface Segmento {
  nome: string;
  destino: Destino;
  marca: Marca;
}

/** Segmentos da barra de progresso, a próxima seção pendente e se a barra some. */
export function pendencias(
  config: ConfigEditavel,
  formulario: Formulario,
  testes: Record<string, ResultadoTeste>,
  pulados: Set<Secao>,
): { segmentos: Segmento[]; proxima: Destino | null; completa: boolean } {
  const repos = reposAtivos(config, formulario);
  const marcas = repos.map((repo) => marcaDe({ repo }, config, formulario, testes, pulados));
  const alvo = repos.find((r) => !temCaminho(formulario, r)) ?? repos[0];
  const segmentos: Segmento[] = [
    {
      nome: GrupoLateral.REPOSITORIOS,
      destino: alvo === undefined ? Secao.NOVO_REPO : { repo: alvo },
      marca: marcas.includes(Marca.PRONTA)
        ? Marca.PRONTA
        : marcas.includes(Marca.FALHOU)
          ? Marca.FALHOU
          : Marca.PENDENTE,
    },
    ...(Object.keys(COBRADAS) as Secao[]).map((s) => ({
      nome: NOME_SECAO[s],
      destino: s,
      marca: marcaDe(s, config, formulario, testes, pulados),
    })),
  ];
  const proxima = segmentos.find((s) => s.marca !== Marca.PRONTA)?.destino ?? null;
  return { segmentos, proxima, completa: proxima === null };
}

/** Seções que este navegador pulou; sem localStorage, nenhuma. */
export function lerPulados(): Set<Secao> {
  try {
    const lidos: unknown = JSON.parse(localStorage.getItem(CHAVE_PULADOS) ?? "[]");
    const validas: string[] = Object.values(Secao);
    return new Set(Array.isArray(lidos) ? (lidos.filter((s) => validas.includes(s)) as Secao[]) : []);
  } catch {
    return new Set();
  }
}

/** Grava os pulos neste navegador; sem localStorage, não faz nada. */
export function gravarPulados(pulados: Set<Secao>): void {
  try {
    localStorage.setItem(CHAVE_PULADOS, JSON.stringify([...pulados]));
  } catch {
    // Aba privada ou bloqueio: o pulo vale só enquanto a modal está aberta.
  }
}
