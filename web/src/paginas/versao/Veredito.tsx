import { Alert, Group, Skeleton, Text } from "@mantine/core";
import type { JSX } from "react";
import type { VerificacaoGravada } from "../../api/tipos";
import { plural } from "../../plural";
import { INTERVALO_RELOGIO_MS, ha, useAgora } from "../../tempo";

const ALTURA_CARREGANDO = 24;

const n = (lista?: unknown[]): number => lista?.length ?? 0;

export function Veredito({
  gravada,
  erro,
}: {
  gravada: VerificacaoGravada | null | undefined;
  erro: Error | null;
}): JSX.Element {
  const agora = useAgora(INTERVALO_RELOGIO_MS);
  if (erro) return <Alert color="red">{erro.message}</Alert>;
  if (gravada === undefined) return <Skeleton height={ALTURA_CARREGANDO} />;
  if (gravada === null)
    return (
      <Text c="dimmed" size="sm">
        não verificada
      </Text>
    );
  const s = gravada.status;
  const cor = s.verde ? "green" : "yellow";
  return (
    <>
      {s.liberada_em != null && (
        <Alert color="cyan" title="Snapshot congelado — não recalculado">
          Liberada em {new Date(s.liberada_em).toLocaleString()}
        </Alert>
      )}
      <Group gap="xs" wrap="wrap">
        <Text c={cor} aria-hidden>
          ●
        </Text>
        <Text fw={700} c={cor}>
          {s.verde ? "VERDE" : "Pendências encontradas"}
        </Text>
        <Text c="dimmed" size="sm">
          {plural(n(s.faltantes), "faltante", "faltantes")} ·{" "}
          {plural(n(s.conflitantes), "conflito", "conflitos")} ·{" "}
          {plural(n(s.suspeitos_conteudo), "suspeito", "suspeitos")} ·{" "}
          {n(s.tasks_sem_commits)} sem commits · escopo +{n(s.tasks_novas)} −
          {n(s.tasks_removidas)} · verificada {ha(gravada.verificado_em, agora)}
        </Text>
      </Group>
    </>
  );
}
