/** "1 faltante", "0 faltantes": a quantidade com a palavra concordando. */
export const plural = (n: number, singular: string, plurais: string): string =>
  `${n} ${n === 1 ? singular : plurais}`;
