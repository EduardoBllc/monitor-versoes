import {
  Alert,
  Badge,
  Code,
  Group,
  NavLink,
  Skeleton,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Metodo, api } from "../api/cliente";
import { EstadoChamado } from "../api/enums";
import type { ChamadoConsultado } from "../api/tipos";

const TAMANHO_HASH = 8;
const LARGURA_LISTA = 260;

enum Rotulo {
  APLICADO = "aplicado",
  SEM_COMMITS = "sem commits",
  PENDENTE = "pendente",
}

// O estado gravado só distingue aplicado de pendente; lista vazia é "sem commits", como na TUI.
function rotulo(c: ChamadoConsultado): { texto: Rotulo; cor: string } {
  if (c.estado === EstadoChamado.APLICADO)
    return { texto: Rotulo.APLICADO, cor: "green" };
  if (c.commits.length === 0) return { texto: Rotulo.SEM_COMMITS, cor: "red" };
  return { texto: Rotulo.PENDENTE, cor: "yellow" };
}

function Detalhe({ chamado }: { chamado: ChamadoConsultado }) {
  const { texto, cor } = rotulo(chamado);
  const q = chamado.commits.length;
  return (
    <Stack gap="sm">
      <Group>
        <Text fw={700}>#{chamado.chamado}</Text>
        <Text c="dimmed">
          {q} commit{q === 1 ? "" : "s"}
        </Text>
        <Badge color={cor}>{texto}</Badge>
      </Group>
      {q === 0 ? (
        <Text c="dimmed">Nenhum commit registrado.</Text>
      ) : (
        <Table>
          <Table.Tbody>
            {/* Mais novo no topo: o consultar entrega o ancestral primeiro. */}
            {[...chamado.commits].reverse().map((c) => (
              <Table.Tr key={c.hash_origem}>
                <Table.Td w={90}>
                  <Code>{c.hash_origem.slice(0, TAMANHO_HASH)}</Code>
                </Table.Td>
                <Table.Td>
                  {c.msg.split("\n")[0] || "mensagem indisponível"}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

export function Consulta({ repo, versao }: { repo: string; versao: string }) {
  const [escolhido, setEscolhido] = useState<string>();
  const { data, error, isLoading } = useQuery({
    queryKey: ["chamados", repo, versao],
    queryFn: () =>
      api<ChamadoConsultado[]>(
        Metodo.GET,
        `/api/repos/${encodeURIComponent(repo)}/versoes/${encodeURIComponent(versao)}/chamados`,
      ),
  });
  if (isLoading) return <Skeleton height={200} />;
  if (error) return <Alert color="red">{error.message}</Alert>;
  if (!data?.length)
    return (
      <Text c="dimmed">
        Nenhum snapshot ainda. Rode Verificar para gerar a consulta.
      </Text>
    );
  const atual = data.find((c) => c.chamado === escolhido) ?? data[0];
  return (
    <Group align="flex-start" wrap="nowrap">
      <Stack gap={0} w={LARGURA_LISTA} style={{ flexShrink: 0 }}>
        {data.map((c) => (
          <NavLink
            key={c.chamado}
            active={c === atual}
            label={`#${c.chamado}`}
            rightSection={
              <Badge color={rotulo(c).cor}>{rotulo(c).texto}</Badge>
            }
            onClick={() => setEscolhido(c.chamado)}
          />
        ))}
      </Stack>
      <div style={{ flex: 1, minWidth: 0 }}>
        {atual && <Detalhe chamado={atual} />}
      </div>
    </Group>
  );
}
