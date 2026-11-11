import { AcaoAlteracao, Escopo } from "./api/enums";
import type { Alteracao, Campo, ConfigEditavel } from "./api/tipos";

export const ORIGEM_MOTOR = "motor";
export const TABELA_AMBIENTE = "ambiente";
export const SEM_ORIGEM = "";

export enum EstadoSegredo {
  DEFINIDO = "definido",
  NAO_DEFINIDO = "nao_definido",
  APAGAR = "apagar",
}

// null no formulário = marcado para apagar; ausente ou "" = não tocado.
export function estadoSegredo(
  valor: Escalar | undefined,
  definido: boolean,
): EstadoSegredo {
  if (valor === null) return EstadoSegredo.APAGAR;
  return definido ? EstadoSegredo.DEFINIDO : EstadoSegredo.NAO_DEFINIDO;
}

export type Escalar = string | number | boolean | null;

// valores: chave de `chaveDe`. Segredo ausente ou "" = não tocado; null = apagar.
export interface Formulario {
  valores: Record<string, Escalar>;
  reposCriados: string[];
  reposRemovidos: string[];
}

export function chaveDe(
  repo: string | null,
  tabela: string | null,
  chave: string,
): string {
  return JSON.stringify([repo, tabela, chave]);
}

function lerChave(k: string): [string | null, string | null, string] {
  return JSON.parse(k) as [string | null, string | null, string];
}

export function achaCampo(
  campos: Campo[],
  repo: string | null,
  tabela: string | null,
  chave: string,
): Campo | undefined {
  return campos.find(
    (c) =>
      c.tabela === tabela &&
      c.chave === chave &&
      (c.escopo === Escopo.REPO) === (repo !== null),
  );
}

const vazio = (v: Escalar | undefined): boolean => v === null || v === "" || v === undefined;

export function alteracoesDe(
  original: ConfigEditavel,
  formulario: Formulario,
): Alteracao[] {
  const lidos = new Map(
    original.valores.map((v) => [chaveDe(v.repo, v.tabela, v.chave), v]),
  );
  const criar: Alteracao[] = formulario.reposCriados.map((repo) => ({
    acao: AcaoAlteracao.CRIAR_REPO,
    repo,
  }));
  const chaves: Alteracao[] = [];
  for (const [k, novo] of Object.entries(formulario.valores)) {
    const [repo, tabela, chave] = lerChave(k);
    if (repo !== null && formulario.reposRemovidos.includes(repo)) continue;
    const lido = lidos.get(k);
    // Valor não escalar (lista, tabela): o servidor devolve null; mexer apagaria.
    if (lido && !lido.editavel) continue;
    const segredo = achaCampo(original.campos, repo, tabela, chave)?.segredo === true;
    const base = { repo, tabela, chave };
    if (segredo) {
      if (novo === null) {
        if (lido?.definido) chaves.push({ acao: AcaoAlteracao.REMOVER, ...base });
      } else if (novo !== "") {
        chaves.push({ acao: AcaoAlteracao.DEFINIR, ...base, valor: novo });
      }
    } else if (vazio(novo)) {
      if (lido?.definido) chaves.push({ acao: AcaoAlteracao.REMOVER, ...base });
    } else if (novo !== lido?.valor) {
      chaves.push({ acao: AcaoAlteracao.DEFINIR, ...base, valor: novo });
    }
  }
  const remover: Alteracao[] = formulario.reposRemovidos
    .filter((repo) => !formulario.reposCriados.includes(repo))
    .map((repo) => ({ acao: AcaoAlteracao.REMOVER_REPO, repo }));
  return [...criar, ...chaves, ...remover];
}
