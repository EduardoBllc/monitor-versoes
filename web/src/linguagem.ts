type Linguagem = { id: string; extensions?: string[]; filenames?: string[] };

const TEXTO_PURO = "plaintext";

// Quem chama passa monaco.languages.getLanguages(): só as linguagens do build.
export function linguagemDe(
  caminho: string,
  linguagens: readonly Linguagem[],
): string {
  const nome = caminho.slice(caminho.lastIndexOf("/") + 1);
  const ponto = nome.lastIndexOf(".");
  const extensao = ponto > 0 ? nome.slice(ponto).toLowerCase() : null;
  const achada = linguagens.find(
    (l) =>
      l.filenames?.includes(nome) ||
      (extensao !== null &&
        l.extensions?.some((e) => e.toLowerCase() === extensao)),
  );
  return achada?.id ?? TEXTO_PURO;
}
