import { Alert, Badge, Code, Group, Stack, Table, Text } from "@mantine/core";
import type { CommitRef, VersionStatus } from "../api/tipos";

const TAMANHO_HASH = 8;

const n = (lista?: unknown[]): number => lista?.length ?? 0;
const hash = (c: CommitRef): string => c.hash_origem.slice(0, TAMANHO_HASH);
const titulo = (c: CommitRef): string => c.msg.split("\n")[0] ?? "";
const plural = (q: number): string => `${q} commit${q === 1 ? "" : "s"}`;

function agrupar(commits: CommitRef[]): Map<string, CommitRef[]> {
  const grupos = new Map<string, CommitRef[]>();
  for (const c of commits) grupos.set(c.chamado, [...(grupos.get(c.chamado) ?? []), c]);
  return grupos;
}

function alertas(s: VersionStatus): string[] {
  const linhas: string[] = [];
  if (n(s.tasks_ambiguas))
    linhas.push(`Chamados em mais de uma versão: ${s.tasks_ambiguas?.join(", ")}`);
  if (n(s.tasks_sem_commits))
    linhas.push(`Chamados sem commits: ${s.tasks_sem_commits?.join(", ")}`);
  if (!s.estado_integro)
    linhas.push(
      `Estado divergente do git: ${(s.commits_sumidos ?? []).map((h) => h.slice(0, TAMANHO_HASH)).join(", ")}`,
    );
  return linhas;
}

function Faltantes({ status }: { status: VersionStatus }) {
  const conflitos = new Set((status.conflitantes ?? []).map((c) => c.hash_origem));
  const suspeitos = new Set((status.suspeitos_conteudo ?? []).map((c) => c.hash_origem));
  return (
    <Stack gap="md">
      {[...agrupar(status.faltantes ?? [])].map(([chamado, itens]) => (
        <div key={chamado}>
          <Text fw={600}>
            #{chamado} · {plural(itens.length)}
          </Text>
          <Table withRowBorders={false}>
            <Table.Tbody>
              {itens.map((c) => (
                <Table.Tr key={c.hash_origem}>
                  <Table.Td w={90}>
                    <Code>{hash(c)}</Code>
                  </Table.Td>
                  <Table.Td>{titulo(c)}</Table.Td>
                  <Table.Td w={200}>
                    {conflitos.has(c.hash_origem) && <Badge color="red">conflitante</Badge>}{" "}
                    {suspeitos.has(c.hash_origem) && <Badge color="yellow">suspeito</Badge>}
                    {!conflitos.has(c.hash_origem) && !suspeitos.has(c.hash_origem) && (
                      <Badge color="gray" variant="light">
                        faltante
                      </Badge>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
      ))}
    </Stack>
  );
}

export function Status({ status, auditado }: { status: VersionStatus; auditado: boolean }) {
  const congelado = status.liberada_em != null && !auditado;
  const avisos = alertas(status);
  const culpados = (status.faltantes ?? []).flatMap((c) => {
    const lista = status.conflito_causado_por?.[c.hash_origem];
    return lista?.length
      ? [`Conflito em ${hash(c)} depende de: ${lista.map((x) => `#${x}`).join(", ")}`]
      : [];
  });
  return (
    <Stack gap="sm">
      {congelado && (
        <Alert color="cyan" title="Snapshot congelado — não recalculado">
          Liberada em {new Date(status.liberada_em ?? "").toLocaleString()}
          {n(status.chamados) > 0 && <Text size="sm">Chamados: {status.chamados?.join(", ")}</Text>}
        </Alert>
      )}
      {auditado && <Alert color="cyan" title="Auditoria da tag — snapshot não alterado" />}
      <Text fw={700} c={status.verde ? "green" : "yellow"}>
        {status.verde ? "VERDE" : "● Pendências encontradas"}
      </Text>
      <Group gap="xs" c="dimmed">
        <span>
          Escopo +{n(status.tasks_novas)} −{n(status.tasks_removidas)}
        </span>
        <span>
          · Git {n(status.faltantes)} faltantes · {n(status.conflitantes)} conflitos
        </span>
        <span>· Sem commits {n(status.tasks_sem_commits)} chamados</span>
      </Group>
      {avisos.length > 0 && (
        <Alert color="yellow">
          {avisos.map((a) => (
            <div key={a}>{a}</div>
          ))}
        </Alert>
      )}
      <Faltantes status={status} />
      {culpados.map((l) => (
        <Text key={l} size="sm">
          {l}
        </Text>
      ))}
    </Stack>
  );
}
