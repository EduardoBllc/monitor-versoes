import { useQuery } from "@tanstack/react-query";
import { Metodo, api } from "./api/cliente";
import { TipoOrigem } from "./api/enums";
import type { Instalacao, PluginInstalado } from "./api/tipos";
import { SECAO_DO_GRUPO, type Secao } from "./configSecoes";

const CHAVE_INSTALACAO = ["instalacao"];

// Uma busca por abertura: quem renova o cache é a checagem em segundo plano.
export const useInstalacao = () =>
  useQuery({
    queryKey: CHAVE_INSTALACAO,
    queryFn: () => api<Instalacao>(Metodo.GET, "/api/instalacao"),
    staleTime: Infinity,
  });

export interface PluginDaSecao {
  plugin: PluginInstalado;
  nova: string | null;
}

export function pluginsDaSecao(i: Instalacao, secao: Secao): PluginDaSecao[] {
  return i.plugins
    .filter((p) => SECAO_DO_GRUPO[p.grupo] === secao)
    .map((plugin) => ({
      plugin,
      // O embutido é o motor: a versão nova dele já está na barra.
      nova:
        plugin.origem.tipo === TipoOrigem.EMBUTIDO
          ? null
          : (i.novidades.find((n) => n.pacote === plugin.pacote)?.nova ?? null),
    }));
}
