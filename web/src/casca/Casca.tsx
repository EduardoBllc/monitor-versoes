import { AppShell, Button, Group, Progress, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, type JSX, type MouseEvent, type ReactNode } from "react";
import type { InscricaoVista } from "../api/tipos";
import { AvisoVersao } from "../componentes/AvisoVersao";
import { ModalResultado } from "../componentes/ModalResultado";
import { PROGRESSO_INICIAL, estaRodando } from "../execucoes";
import {
  INTERVALO_CONSULTA_INSCRICOES_MS,
  avisos,
  consultaInscricoes,
} from "../inscricoes";
import { useInstalacao } from "../instalacao";
import { Link, ir, useRota } from "../navegacao";
import { useOperacoes } from "../operacoes/OperacoesProvider";
import { Pagina, alvoDa, caminhoDa } from "../rotas";
import { FONTE_MONO } from "../tema";
import { Trilha } from "./Trilha";

const ALTURA_CABECALHO = 44;
const LARGURA_PROGRESSO = 120;
const PERCENTUAL = 100;

function ProgressoDoRepo({ repo }: { repo: string }) {
  const { execucoes } = useOperacoes();
  if (!estaRodando(execucoes, repo)) return null;
  const { fase, feito, total } = execucoes.progresso[repo] ?? PROGRESSO_INICIAL;
  return (
    <Group gap="xs" wrap="nowrap">
      <Progress
        w={LARGURA_PROGRESSO}
        size="sm"
        value={total > 0 ? (feito / total) * PERCENTUAL : PERCENTUAL}
        animated={total === 0}
        striped={total === 0}
      />
      <Text size="xs" c="dimmed" truncate>
        {fase}
      </Text>
    </Group>
  );
}

// Avisa as mudanças das rodadas agendadas em qualquer página.
function useAvisosDasInscricoes() {
  const vistas = useQuery({
    ...consultaInscricoes,
    refetchInterval: INTERVALO_CONSULTA_INSCRICOES_MS,
  });
  // Ref, não state: o efeito duplo do StrictMode não pode avisar a mesma mudança duas vezes.
  const anteriores = useRef<InscricaoVista[] | undefined>(undefined);
  useEffect(() => {
    const depois = vistas.data;
    if (depois === undefined) return;
    for (const a of avisos(anteriores.current, depois))
      notifications.show({ title: a.titulo, message: a.mensagem, color: a.cor });
    anteriores.current = depois;
  }, [vistas.data]);
}

export function Casca({ children }: { children: ReactNode }): JSX.Element {
  const operacoes = useOperacoes();
  const { repo } = alvoDa(useRota());
  const instalacao = useInstalacao();
  useAvisosDasInscricoes();
  return (
    <AppShell header={{ height: ALTURA_CABECALHO }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" gap="md" wrap="nowrap">
          <Link para={{ pagina: Pagina.INICIO }} ff={FONTE_MONO} fw={600} c="white" underline="never">
            monitor-versoes
          </Link>
          <Trilha />
          {repo !== undefined && <ProgressoDoRepo repo={repo} />}
          <Group gap="xs" ml="auto" wrap="nowrap">
            <AvisoVersao novidades={instalacao.data?.novidades ?? []} />
            <Button
              variant="default"
              component="a"
              href={caminhoDa({ pagina: Pagina.CONFIG })}
              onClick={(e: MouseEvent) => {
                e.preventDefault();
                ir({ pagina: Pagina.CONFIG });
              }}
              disabled={repo !== undefined && estaRodando(operacoes.execucoes, repo)}
            >
              Configuração
            </Button>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>{children}</AppShell.Main>
      <ModalResultado
        resultado={operacoes.resultado}
        aoFechar={operacoes.fecharResultado}
      />
    </AppShell>
  );
}
