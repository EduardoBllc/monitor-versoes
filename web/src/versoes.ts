import { useQuery } from "@tanstack/react-query";
import { Metodo, api } from "./api/cliente";
import type { VersaoListada } from "./api/tipos";

export enum OrigemVersoes {
  GRAVADAS = "gravadas",
  FETCH = "fetch",
}

// O prefixo ["versoes", repo] é o que o fim de uma operação invalida: cobre as duas origens.
export const chaveVersoes = (repo: string, origem: OrigemVersoes) =>
  ["versoes", repo, origem] as const;

const SO_GRAVADAS = "?gravadas=true";

const consulta = (repo: string, origem: OrigemVersoes, habilitado: boolean) => ({
  queryKey: chaveVersoes(repo, origem),
  queryFn: () =>
    api<VersaoListada[]>(
      Metodo.GET,
      `/api/repos/${encodeURIComponent(repo)}/versoes${
        origem === OrigemVersoes.GRAVADAS ? SO_GRAVADAS : ""
      }`,
    ),
  enabled: habilitado,
});

// A lista com fetch faz git fetch no repo: a gravada aparece antes e é substituída quando ela chega.
export function useVersoes(
  repo: string,
  habilitado: boolean,
): { versoes: VersaoListada[] | undefined; buscando: boolean; erro: Error | null } {
  const gravadas = useQuery(consulta(repo, OrigemVersoes.GRAVADAS, habilitado));
  const comFetch = useQuery(consulta(repo, OrigemVersoes.FETCH, habilitado));
  return {
    versoes: comFetch.data ?? gravadas.data,
    buscando: comFetch.isFetching,
    erro: comFetch.error ?? gravadas.error,
  };
}

export const emAberto = (v: VersaoListada[]) => v.filter((x) => !x.liberada);
