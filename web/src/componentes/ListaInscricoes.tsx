import { Group, Paper, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import type { JSX } from "react";
import { consultaInscricoes } from "../inscricoes";
import { Link } from "../navegacao";
import { Pagina } from "../rotas";
import { FONTE_MONO } from "../tema";
import { INTERVALO_RELOGIO_MS, ha, useAgora } from "../tempo";

const TITULO = "Inscrições";

/** As inscrições de todos os repos, ou só as do `repo`. */
export function ListaInscricoes({ repo }: { repo?: string }): JSX.Element {
  // A casca consulta a mesma chave a cada 15 s: esta lista vem junto.
  const inscricoes = useQuery(consultaInscricoes);
  const agora = useAgora(INTERVALO_RELOGIO_MS);
  const lista = (inscricoes.data ?? []).filter(
    (i) => repo === undefined || i.repo === repo,
  );
  return (
    <Paper component="section" aria-label={TITULO} px="md" py="sm">
      <Stack gap="xs">
        <Text size="xs" fw={600} tt="uppercase" c="dimmed">
          {TITULO}
        </Text>
        {inscricoes.isSuccess && lista.length === 0 && (
          <Text size="sm" c="dimmed">
            nenhuma inscrição
          </Text>
        )}
        {lista.map((i) => (
          <Group key={`${i.repo}@${i.versao}`} gap="xs" justify="space-between" wrap="nowrap">
            <Group gap="xs" wrap="nowrap">
              {repo === undefined && <Text size="sm">{i.repo}</Text>}
              <Link
                para={{ pagina: Pagina.VERSAO, repo: i.repo, versao: i.versao }}
                ff={FONTE_MONO}
                size="sm"
              >
                {i.versao}
              </Link>
              <Text size="xs" c="dimmed">
                a cada {i.intervalo}
              </Text>
            </Group>
            <Text size="xs" c="dimmed" ff={FONTE_MONO}>
              {i.ultima === null
                ? "nunca executou"
                : `${i.ultima.desfecho} ${ha(i.ultima.hora, agora)}`}
            </Text>
          </Group>
        ))}
      </Stack>
    </Paper>
  );
}
