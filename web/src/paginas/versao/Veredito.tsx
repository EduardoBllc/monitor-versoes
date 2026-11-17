import { Alert, Group, Text } from "@mantine/core";
import type { JSX } from "react";
import type { VerificacaoGravada } from "../../api/tipos";

const MS_POR_MINUTO = 60_000;
const MINUTOS_POR_HORA = 60;
const HORAS_POR_DIA = 24;
const relativo = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });

function haQuanto(iso: string): string {
  const minutos = Math.round((Date.parse(iso) - Date.now()) / MS_POR_MINUTO);
  const horas = Math.round(minutos / MINUTOS_POR_HORA);
  if (Math.abs(minutos) < MINUTOS_POR_HORA)
    return relativo.format(minutos, "minute");
  if (Math.abs(horas) < HORAS_POR_DIA) return relativo.format(horas, "hour");
  return relativo.format(Math.round(horas / HORAS_POR_DIA), "day");
}

const n = (lista?: unknown[]): number => lista?.length ?? 0;

export function Veredito({
  gravada,
}: {
  gravada: VerificacaoGravada | null | undefined;
}): JSX.Element {
  if (!gravada)
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
          {n(s.faltantes)} faltantes · {n(s.conflitantes)} conflitos ·{" "}
          {n(s.suspeitos_conteudo)} suspeitos · {n(s.tasks_sem_commits)} sem
          commits · escopo +{n(s.tasks_novas)} −{n(s.tasks_removidas)} ·
          verificada {haQuanto(gravada.verificado_em)}
        </Text>
      </Group>
    </>
  );
}
