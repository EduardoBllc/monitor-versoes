import { useQuery } from "@tanstack/react-query";
import { Metodo, api } from "./api/cliente";
import type { GrupoPlugin } from "./api/enums";
import type { Instalacao, Novidade, PluginInstalado } from "./api/tipos";
import { SECAO_DO_GRUPO, type Secao } from "./configSecoes";

// PACOTE_MOTOR em motor/instalacao.py.
export const PACOTE_MOTOR = "monitor-versoes";
const CHAVE_INSTALACAO = ["instalacao"];

// Uma busca por abertura: quem renova o cache é a checagem em segundo plano.
export const useInstalacao = () =>
  useQuery({
    queryKey: CHAVE_INSTALACAO,
    queryFn: () => api<Instalacao>(Metodo.GET, "/api/instalacao"),
    staleTime: Infinity,
  });

/** O aviso do terminal (linha_aviso em motor/novidades.py) sem o comando. */
export function textoAviso(n: Novidade): string {
  const prefixo = n.pacote === PACOTE_MOTOR ? "" : `${n.pacote}: `;
  return `${prefixo}Versão ${n.nova} disponível (você tem ${n.atual}):`;
}

export interface PluginDaSecao {
  plugin: PluginInstalado;
  nova: string | null;
}

export function pluginsDaSecao(i: Instalacao, secao: Secao): PluginDaSecao[] {
  return i.plugins
    // O tipo gerado é string; o enum espelha os grupos do motor.
    .filter((p) => SECAO_DO_GRUPO[p.grupo as GrupoPlugin] === secao)
    .map((plugin) => ({
      plugin,
      nova: i.novidades.find((n) => n.pacote === plugin.pacote)?.nova ?? null,
    }));
}
