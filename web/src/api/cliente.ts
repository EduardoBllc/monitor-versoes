import { TipoErro } from "./enums";
import type { RepoOption, VersaoListada } from "./tipos";

export class ErroApi extends Error {
  constructor(
    readonly tipo: TipoErro,
    mensagem: string,
    readonly status: number,
  ) {
    super(mensagem);
  }
}

export enum Metodo {
  GET = "GET",
  POST = "POST",
  PUT = "PUT",
  DELETE = "DELETE",
}

export const CHAVE_REPOS = ["repos"];

export const consultaRepos = {
  queryKey: CHAVE_REPOS,
  queryFn: () => api<RepoOption[]>(Metodo.GET, "/api/repos"),
};

// Cada leitura faz git fetch no repo.
export const consultaVersoes = (repo: string) => ({
  queryKey: ["versoes", repo],
  queryFn: () =>
    api<VersaoListada[]>(
      Metodo.GET,
      `/api/repos/${encodeURIComponent(repo)}/versoes`,
    ),
});

const STATUS_ERRO_MIN = 400;
const STATUS_SEM_CORPO = 204;

export async function api<T>(
  metodo: Metodo,
  caminho: string,
  corpo?: unknown,
): Promise<T> {
  const resposta = await fetch(caminho, {
    method: metodo,
    headers: corpo === undefined ? undefined : { "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  if (resposta.status >= STATUS_ERRO_MIN) {
    const erro = (await resposta.json().catch(() => ({}))) as {
      tipo?: TipoErro;
      mensagem?: string;
    };
    throw new ErroApi(
      erro.tipo ?? TipoErro.INTERNO,
      erro.mensagem ?? resposta.statusText,
      resposta.status,
    );
  }
  if (resposta.status === STATUS_SEM_CORPO) return undefined as T;
  return (await resposta.json()) as T;
}
