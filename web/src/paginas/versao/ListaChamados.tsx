import {
  Alert,
  Badge,
  Code,
  Group,
  SegmentedControl,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  UnstyledButton,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState, type JSX } from "react";
import { Metodo, api } from "../../api/cliente";
import { EstadoChamado } from "../../api/enums";
import type { ChamadoConsultado, VersionStatus } from "../../api/tipos";
import { plural } from "../../plural";
import { FONTE_MONO, TAMANHO_HASH } from "../../tema";
import { chaveChamados } from "../../versoes";
import {
  MotivoCommit,
  filtrarChamados,
  verChamados,
  type ChamadoVisto,
} from "./chamados";

enum Filtro {
  TODOS = "todos",
}

const SEM_COMMITS = "sem commits";
const LARGURA_HASH = 90;

const COR_MOTIVO: Record<MotivoCommit, string> = {
  [MotivoCommit.PRESENTE]: "green",
  [MotivoCommit.FALTA]: "orange",
  [MotivoCommit.CONFLITA]: "red",
  [MotivoCommit.SUSPEITO]: "yellow",
};

// O estado gravado só distingue aplicado de pendente; lista vazia é "sem commits", como na TUI.
function rotulo(c: ChamadoVisto): { texto: string; cor: string } {
  if (c.estado === EstadoChamado.APLICADO) return { texto: c.estado, cor: "green" };
  if (c.semCommits) return { texto: SEM_COMMITS, cor: "red" };
  return { texto: c.estado, cor: "yellow" };
}

function Linha({ chamado }: { chamado: ChamadoVisto }): JSX.Element {
  const [aberto, setAberto] = useState(false);
  const { texto, cor } = rotulo(chamado);
  const q = chamado.commits.length;
  return (
    <div>
      <UnstyledButton
        w="100%"
        py={4}
        aria-expanded={aberto}
        onClick={() => setAberto((a) => !a)}
      >
        <Group gap="xs">
          <Text c="dimmed" aria-hidden>
            {aberto ? "▾" : "▸"}
          </Text>
          <Text fw={700}>#{chamado.chamado}</Text>
          <Text c="dimmed">· {plural(q, "commit", "commits")}</Text>
          <Badge color={cor} variant="light">
            {texto}
          </Badge>
        </Group>
      </UnstyledButton>
      {aberto &&
        (q === 0 ? (
          <Text c="dimmed" pl="lg">
            Nenhum commit registrado.
          </Text>
        ) : (
          <Table withRowBorders={false} pl="lg">
            <Table.Tbody>
              {/* Mais novo no topo: o consultar entrega o ancestral primeiro. */}
              {[...chamado.commits].reverse().map((c) => (
                <Table.Tr key={c.hash}>
                  <Table.Td w={LARGURA_HASH}>
                    <Code ff={FONTE_MONO}>{c.hash.slice(0, TAMANHO_HASH)}</Code>
                  </Table.Td>
                  {/* O título leva a sobra: o motivo fecha a linha à direita. */}
                  <Table.Td w="100%">{c.titulo || "mensagem indisponível"}</Table.Td>
                  <Table.Td ta="right" style={{ whiteSpace: "nowrap" }}>
                    {c.motivo && (
                      // O rótulo do Badge encolhe a zero numa célula de largura mínima.
                      <Badge color={COR_MOTIVO[c.motivo]} variant="light" miw="max-content">
                        {c.motivo}
                      </Badge>
                    )}
                    {c.dependeDe.length > 0 && (
                      <Text span c="dimmed" size="sm" ml="xs">
                        depende de {c.dependeDe.map((x) => `#${x}`).join(", ")}
                      </Text>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ))}
    </div>
  );
}

export function ListaChamados({
  repo,
  versao,
  status,
}: {
  repo: string;
  versao: string;
  status: VersionStatus | null;
}): JSX.Element {
  const [estado, setEstado] = useState<Filtro | EstadoChamado>(Filtro.TODOS);
  const [busca, setBusca] = useState("");
  const { data, error, isLoading } = useQuery({
    queryKey: chaveChamados(repo, versao),
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
  const lista = filtrarChamados(
    verChamados(data, status),
    estado === Filtro.TODOS ? null : estado,
    busca,
  );
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <SegmentedControl
          size="xs"
          value={estado}
          onChange={setEstado}
          data={[Filtro.TODOS, EstadoChamado.APLICADO, EstadoChamado.PENDENTE]}
        />
        <TextInput
          size="xs"
          placeholder="#chamado, hash ou título"
          aria-label="Buscar chamado"
          value={busca}
          onChange={(e) => setBusca(e.currentTarget.value)}
        />
      </Group>
      {lista.length === 0 && <Text c="dimmed">Nenhum chamado encontrado.</Text>}
      {lista.map((c) => (
        <Linha key={c.chamado} chamado={c} />
      ))}
    </Stack>
  );
}
