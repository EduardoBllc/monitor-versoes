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

export const blocoEm = (texto: string, inicio: number): Bloco | undefined =>
  blocos(texto).find((b) => b.inicio === inicio);

function trecho(bloco: Bloco, lado: Lado): string {
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

export function aceitar(texto: string, bloco: Bloco, lado: Lado): string {
  const linhas = linhasDe(texto);
  const antes = linhas.slice(0, bloco.inicio - 1).map((l) => l + QUEBRA);
  const depois = linhas.slice(bloco.fim);
  const novo = trecho(bloco, lado);
  // Bloco na última linha, sem quebra final: o trecho também termina sem ela.
  const meio = depois.length === 0 ? novo.replace(/\r?\n$/, "") : novo;
  return antes.join("") + meio + depois.join(QUEBRA);
}
