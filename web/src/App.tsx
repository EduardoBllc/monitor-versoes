import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { JSX } from "react";
import { Casca } from "./casca/Casca";
import { useRota } from "./navegacao";
import { chaveVersao } from "./operacoes/chave";
import { OperacoesProvider } from "./operacoes/OperacoesProvider";
import { PaginaInicio } from "./paginas/PaginaInicio";
import { PaginaRepo } from "./paginas/PaginaRepo";
import { PaginaVersao } from "./paginas/PaginaVersao";
import { Pagina } from "./rotas";
import { tema } from "./tema";

// Sem refetch ao voltar do editor nem retry: cada leitura de versões faz git fetch.
const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } },
});

function Roteador(): JSX.Element {
  const rota = useRota();
  switch (rota.pagina) {
    // A configuração ainda abre no modal da casca.
    case Pagina.INICIO:
    case Pagina.CONFIG:
      return <PaginaInicio />;
    case Pagina.REPO:
      return <PaginaRepo key={rota.repo} repo={rota.repo} />;
    case Pagina.VERSAO:
      return (
        <PaginaVersao
          key={chaveVersao(rota.repo, rota.versao)}
          repo={rota.repo}
          versao={rota.versao}
        />
      );
  }
}

export function App(): JSX.Element {
  return (
    <MantineProvider theme={tema} forceColorScheme="dark">
      <QueryClientProvider client={queryClient}>
        <Notifications />
        <OperacoesProvider>
          <Casca>
            <Roteador />
          </Casca>
        </OperacoesProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
