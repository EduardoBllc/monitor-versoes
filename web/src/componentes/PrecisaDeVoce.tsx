import { Button, Group, Paper, Stack, Text } from "@mantine/core";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useState, type JSX } from "react";
import { Metodo, api } from "../api/cliente";
import type { Execucao } from "../api/eventos";
import { consultaInscricoes } from "../inscricoes";
import { Link } from "../navegacao";
import {
  TipoPendencia,
  dispensar,
  itensPendentes,
  lerDispensados,
} from "../precisaDeVoce";
import { Pagina } from "../rotas";
import { FONTE_MONO } from "../tema";

export const INTERVALO_EXECUCAO_MS = 5_000;
const CHAVE_PENDENCIAS = "pendencias";
const TITULO = "Precisa de você";
const SEPARADOR_DETALHE = ", ";

const TEXTO: Record<TipoPendencia, string> = {
  [TipoPendencia.BLOQUEIO]: "atualização bloqueada",
  [TipoPendencia.VERMELHOS]: "vermelhos na última rodada",
};

export function PrecisaDeVoce({ repos }: { repos: string[] }): JSX.Element | null {
  // Pendências vivem na memória do daemon e mudam sem a web operar (outra aba, fim de execução).
  const pendencias = useQueries({
    queries: repos.map((repo) => ({
      queryKey: [CHAVE_PENDENCIAS, repo],
      queryFn: () =>
        api<Execucao[]>(Metodo.GET, `/api/repos/${encodeURIComponent(repo)}/pendencias`),
      refetchInterval: INTERVALO_EXECUCAO_MS,
    })),
    combine: (rs) => rs.flatMap((r) => r.data ?? []),
  });
  const inscricoes = useQuery(consultaInscricoes);
  const [dispensados, setDispensados] = useState(lerDispensados);
  const itens = itensPendentes(pendencias, inscricoes.data ?? [], dispensados);
  if (itens.length === 0) return null;
  return (
    <Paper component="section" aria-label={TITULO} px="md" py="sm" bd="1px solid red.9">
      <Stack gap="xs">
        <Text size="xs" fw={600} tt="uppercase" c="red.4">
          ⚠ {TITULO}
        </Text>
        <Stack component="ul" gap="xs" p={0} m={0} style={{ listStyle: "none" }}>
          {itens.map((i) => (
            <Group component="li" key={i.chave} gap="xs" wrap="nowrap">
              <Text size="sm" flex={1}>
                {i.repo}{" "}
                <Text span inherit ff={FONTE_MONO} fw={600}>
                  {i.versao}
                </Text>
                : {TEXTO[i.tipo]}{" "}
                <Text span size="xs" c="dimmed">
                  {i.detalhe.join(SEPARADOR_DETALHE)}
                </Text>
              </Text>
              {i.tipo === TipoPendencia.BLOQUEIO ? (
                <Link para={{ pagina: Pagina.VERSAO, repo: i.repo, versao: i.versao }} size="sm">
                  Resolver
                </Link>
              ) : (
                <Button variant="default" onClick={() => setDispensados(dispensar(i.chave))}>
                  Dispensar
                </Button>
              )}
            </Group>
          ))}
        </Stack>
      </Stack>
    </Paper>
  );
}
