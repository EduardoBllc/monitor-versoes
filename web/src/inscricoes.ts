import { queryOptions } from "@tanstack/react-query";
import { Metodo, api } from "./api/cliente";
import { Desfecho } from "./api/enums";
import type { InscricaoVista } from "./api/tipos";

export const INTERVALO_CONSULTA_INSCRICOES_MS = 15_000;

export const consultaInscricoes = queryOptions({
  queryKey: ["inscricoes"],
  queryFn: () => api<InscricaoVista[]>(Metodo.GET, "/api/inscricoes"),
});

export enum CorAviso {
  VERDE = "green",
  LARANJA = "orange",
  VERMELHO = "red",
}

export interface Aviso {
  titulo: string;
  mensagem: string;
  cor: CorAviso;
}

const chaveDe = (i: InscricaoVista): string => `${i.repo}@${i.versao}`;

// Espelha eventos() do motor: o que o daemon decide avisar no desktop, a web avisa aqui.
export function avisos(
  antes: InscricaoVista[] | undefined,
  depois: InscricaoVista[],
): Aviso[] {
  if (antes === undefined) return [];
  const anteriores = new Map(antes.map((i) => [chaveDe(i), i]));
  return depois.flatMap((atual) => {
    const anterior = anteriores.get(chaveDe(atual));
    const ultima = atual.ultima;
    if (anterior === undefined || ultima === null) return [];
    if (anterior.ultima?.hora === ultima.hora) return [];
    const titulo = `${atual.versao} · ${atual.repo}`;
    const com = (texto: string): string =>
      ultima.mensagem ? `${texto}: ${ultima.mensagem}` : texto;
    const saida: Aviso[] = [];
    switch (ultima.desfecho) {
      case Desfecho.APLICOU:
        saida.push({
          titulo,
          mensagem: com("aplicou"),
          cor: CorAviso.VERDE,
        });
        break;
      case Desfecho.BLOQUEADA:
        saida.push({
          titulo,
          mensagem: com("bloqueada (conflito)"),
          cor: CorAviso.LARANJA,
        });
        break;
      case Desfecho.ERRO:
        if (anterior.ultima?.desfecho_aviso !== Desfecho.ERRO)
          saida.push({
            titulo,
            mensagem: com("erro"),
            cor: CorAviso.VERMELHO,
          });
        break;
      default:
    }
    const conhecidos = new Set(anterior.ultima?.vermelhos ?? []);
    const novos = ultima.vermelhos.filter((v) => !conhecidos.has(v));
    if (novos.length > 0)
      saida.push({
        titulo,
        mensagem: `novos vermelhos: ${novos.join(", ")}`,
        cor: CorAviso.LARANJA,
      });
    return saida;
  });
}
