const LOCALE = "pt-BR";
const relativo = new Intl.RelativeTimeFormat(LOCALE);

// Da maior para a menor: a primeira que cabe no intervalo é a usada.
const UNIDADES: readonly [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400_000],
  ["hour", 3_600_000],
  ["minute", 60_000],
  ["second", 1_000],
];
const MENOR = UNIDADES[UNIDADES.length - 1]!;

/** "há 3 minutos": quanto tempo passou desde o instante ISO. */
export function ha(iso: string, agora = Date.now()): string {
  // Relógio do servidor adiantado não vira "daqui a".
  const passado = Math.max(0, agora - Date.parse(iso));
  const [unidade, ms] = UNIDADES.find(([, ms]) => passado >= ms) ?? MENOR;
  return relativo.format(-Math.floor(passado / ms), unidade);
}
