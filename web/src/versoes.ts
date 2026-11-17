import { useQuery, type QueryClient } from "@tanstack/react-query";
import { Metodo, api } from "./api/cliente";
import type { VersaoListada } from "./api/tipos";

export enum OrigemVersoes {
  GRAVADAS = "gravadas",
  FETCH = "fetch",
}

// Sem git, é barata: acompanha as verificações das rodadas agendadas.
const INTERVALO_GRAVADAS_MS = 15_000;

const chaveVersoes = (repo: string, origem: OrigemVersoes) =>
  ["versoes", repo, origem] as const;

export const chaveVerificacao = (repo: string, versao: string) =>
  ["verificacao", repo, versao] as const;

export const chaveChamados = (repo: string, versao: string) =>
  ["chamados", repo, versao] as const;

/** Releitura do que uma execução gravou na versão; a lista com fetch fica de fora (git fetch). */
export function invalidarGravadas(cliente: QueryClient, repo: string, versao: string): void {
  void cliente.invalidateQueries({
    queryKey: chaveVersoes(repo, OrigemVersoes.GRAVADAS),
    exact: true,
  });
  void cliente.invalidateQueries({ queryKey: chaveVerificacao(repo, versao), exact: true });
}

export function invalidarFetch(cliente: QueryClient, repo: string): void {
  void cliente.invalidateQueries({
    queryKey: chaveVersoes(repo, OrigemVersoes.FETCH),
    exact: true,
  });
}

const SO_GRAVADAS = "?gravadas=true";

export const consultaVersoes = (repo: string, origem: OrigemVersoes) => ({
  queryKey: chaveVersoes(repo, origem),
  queryFn: () =>
    api<VersaoListada[]>(
      Metodo.GET,
      `/api/repos/${encodeURIComponent(repo)}/versoes${
        origem === OrigemVersoes.GRAVADAS ? SO_GRAVADAS : ""
      }`,
    ),
});

// Quais versões existem e se estão liberadas é do fetch; verificação e atualização, da
// gravada, que o polling mantém mais nova.
export function juntarVersoes(
  gravadas: VersaoListada[] | undefined,
  comFetch: VersaoListada[] | undefined,
): VersaoListada[] | undefined {
  if (comFetch === undefined) return gravadas;
  const porNumero = new Map(gravadas?.map((v) => [v.numero, v]));
  return comFetch.map((v) => {
    const g = porNumero.get(v.numero);
    return g ? { ...v, atualizada_em: g.atualizada_em, verificacao: g.verificacao } : v;
  });
}

// A lista com fetch faz git fetch no repo: a gravada aparece antes e é substituída quando ela chega.
export function useVersoes(
  repo: string,
  habilitado: boolean,
): { versoes: VersaoListada[] | undefined; buscando: boolean; erro: Error | null } {
  const gravadas = useQuery({
    ...consultaVersoes(repo, OrigemVersoes.GRAVADAS),
    enabled: habilitado,
    refetchInterval: INTERVALO_GRAVADAS_MS,
  });
  const comFetch = useQuery({
    ...consultaVersoes(repo, OrigemVersoes.FETCH),
    enabled: habilitado,
  });
  return {
    versoes: juntarVersoes(gravadas.data, comFetch.data),
    buscando: comFetch.isFetching,
    erro: comFetch.error ?? gravadas.error,
  };
}

export const emAberto = (v: VersaoListada[]) => v.filter((x) => !x.liberada);
