const SEPARADOR = "@";

export const prefixoRepo = (repo: string): string => `${repo}${SEPARADOR}`;

export const chaveVersao = (repo: string, versao: string): string =>
  `${prefixoRepo(repo)}${versao}`;
