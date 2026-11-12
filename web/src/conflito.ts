import { assertNever } from "./api/enums";

export enum Lado {
  OURS = "ours",
  THEIRS = "theirs",
  AMBOS = "ambos",
  BASE = "base",
}

enum Marcador {
  INICIO = "<<<<<<<",
  BASE = "|||||||",
  MEIO = "=======",
  FIM = ">>>>>>>",
}

enum Secao {
  OURS,
  BASE,
  THEIRS,
}

export type Bloco = {
  inicio: number;
  fim: number;
  ours: string;
  base: string | null;
  theirs: string;
};

export const AVISO_DESCARTE =
  "A edição não marcada como resolvida será descartada.";
const TAMANHO_MARCADOR = 7;
const QUEBRA = "\n";
const MARCADORES: readonly string[] = Object.values(Marcador);

// Mesma regra de motor/domain/conflito.py: 7 caracteres, depois fim de linha ou espaço.
function marcador(linha: string): Marcador | null {
  const l = linha.endsWith("\r") ? linha.slice(0, -1) : linha;
  const m = l.slice(0, TAMANHO_MARCADOR);
  if (!MARCADORES.includes(m)) return null;
  return l.length === TAMANHO_MARCADOR || l[TAMANHO_MARCADOR] === " "
    ? (m as Marcador)
    : null;
}

// Só "\n" quebra linha, como no git e no motor; split por regex aceitaria outros separadores.
const linhasDe = (texto: string): string[] => texto.split(QUEBRA);

export function temMarcadores(texto: string): boolean {
  return linhasDe(texto).some((l) => marcador(l) !== null);
}

export function blocos(texto: string): Bloco[] {
  const achados: Bloco[] = [];
  let aberto: { inicio: number; secoes: Map<Secao, string[]> } | null = null;
  let secao = Secao.OURS;
  const juntar = (s: Secao) =>
    aberto?.secoes
      .get(s)
      ?.map((l) => l + QUEBRA)
      .join("") ?? null;
  linhasDe(texto).forEach((linha, i) => {
    const m = marcador(linha);
    if (m === Marcador.INICIO) {
      aberto = { inicio: i + 1, secoes: new Map([[Secao.OURS, []]]) };
      secao = Secao.OURS;
    } else if (aberto === null) {
      return;
    } else if (m === Marcador.BASE && secao === Secao.OURS) {
      secao = Secao.BASE;
      aberto.secoes.set(secao, []);
    } else if (m === Marcador.MEIO && secao !== Secao.THEIRS) {
      secao = Secao.THEIRS;
      aberto.secoes.set(secao, []);
    } else if (m === Marcador.FIM && secao === Secao.THEIRS) {
      achados.push({
        inicio: aberto.inicio,
        fim: i + 1,
        ours: juntar(Secao.OURS) ?? "",
        base: juntar(Secao.BASE),
        theirs: juntar(Secao.THEIRS) ?? "",
      });
      aberto = null;
    } else {
      aberto.secoes.get(secao)?.push(linha);
    }
  });
  return achados;
}

export function trecho(bloco: Bloco, lado: Lado): string {
  switch (lado) {
    case Lado.OURS:
      return bloco.ours;
    case Lado.THEIRS:
      return bloco.theirs;
    case Lado.AMBOS:
      return bloco.ours + bloco.theirs;
    case Lado.BASE:
      if (bloco.base === null) throw new Error("bloco sem seção base");
      return bloco.base;
    default:
      return assertNever(lado);
  }
}

// Linhas começando em 1, intervalo fechado; fim === inicio - 1 é faixa vazia,
// ancorada antes de `inicio`.
export type Faixa = { inicio: number; fim: number };

export const CONTEXTO = 3;

// Linhas de um trecho que termina em quebra: o último "" do split não é linha.
const linhasDoTrecho = (trecho: string): string[] =>
  trecho === "" ? [] : linhasDe(trecho.replace(/\n$/, ""));

// ponytail: busca por conteúdo, em ordem; conteúdo repetido pode casar cedo, e o
// cursor que só avança atenua. Merge de 3 vias no browser se isso pesar.
export function localizar(arquivo: string, trechos: string[]): Faixa[] {
  const linhas = linhasDe(arquivo);
  let cursor = 1;
  return trechos.map((t) => {
    const procuradas = linhasDoTrecho(t);
    const n = procuradas.length;
    for (let i = cursor - 1; n > 0 && i + n <= linhas.length; i++) {
      if (procuradas.every((l, j) => linhas[i + j] === l)) {
        cursor = i + n + 1;
        return { inicio: i + 1, fim: i + n };
      }
    }
    return { inicio: cursor, fim: cursor - 1 };
  });
}

export function recolher(
  total: number,
  visiveis: Faixa[],
  contexto: number,
): Faixa[] {
  if (visiveis.length === 0) return [];
  const abertas = visiveis
    .map((f) => ({
      inicio: Math.max(1, f.inicio - contexto),
      fim: Math.min(total, f.fim + contexto),
    }))
    .sort((a, b) => a.inicio - b.inicio);
  const ocultas: Faixa[] = [];
  let proxima = 1;
  for (const a of [...abertas, { inicio: total + 1, fim: total }]) {
    // Esconder uma linha só custa o mesmo espaço que o aviso "⋯ 1 linha".
    if (a.inicio - proxima >= 2)
      ocultas.push({ inicio: proxima, fim: a.inicio - 1 });
    proxima = Math.max(proxima, a.fim + 1);
  }
  return ocultas;
}

export enum EstadoBloco {
  ABERTO = "aberto",
  DECIDIDO = "decidido",
  EDITADO = "editado",
}

// `texto` é o que o Aceitar gravou no lugar do bloco.
export type Decisao = { lado: Lado; texto: string };

export function estadoDoBloco(
  atual: string,
  decisao: Decisao | null,
): EstadoBloco {
  if (decisao !== null && atual === decisao.texto) return EstadoBloco.DECIDIDO;
  return temMarcadores(atual) ? EstadoBloco.ABERTO : EstadoBloco.EDITADO;
}

export const aceitouLado = (
  decisao: Decisao | null,
  lado: Lado.OURS | Lado.THEIRS,
): boolean => decisao?.lado === lado || decisao?.lado === Lado.AMBOS;

type SecaoDoBloco = { faixa: Faixa; lado: Lado.OURS | Lado.BASE | Lado.THEIRS | null };

// Linhas de cada marcador (lado null) e de cada seção do bloco, para colorir.
export function secoesDoBloco(bloco: Bloco): SecaoDoBloco[] {
  const secoes: SecaoDoBloco[] = [];
  let linha = bloco.inicio;
  const marcador = () => {
    secoes.push({ faixa: { inicio: linha, fim: linha }, lado: null });
    linha++;
  };
  const secao = (lado: Lado.OURS | Lado.BASE | Lado.THEIRS, texto: string) => {
    const n = linhasDoTrecho(texto).length;
    secoes.push({ faixa: { inicio: linha, fim: linha + n - 1 }, lado });
    linha += n;
  };
  marcador();
  secao(Lado.OURS, bloco.ours);
  if (bloco.base !== null) {
    marcador();
    secao(Lado.BASE, bloco.base);
  }
  marcador();
  secao(Lado.THEIRS, bloco.theirs);
  marcador();
  return secoes;
}
