import { Progress } from "@mantine/core";
import type { JSX } from "react";

const LARGURA = 120;
const PERCENTUAL = 100;

enum CorSegmento {
  PRESENTES = "green",
  FALTANTES = "yellow",
  CONFLITANTES = "red",
}

export function BarraSegmentada({
  presentes,
  faltantes,
  conflitantes,
}: {
  presentes: number;
  faltantes: number;
  conflitantes: number;
}): JSX.Element {
  const total = presentes + faltantes + conflitantes;
  const segmentos: [CorSegmento, number][] = [
    [CorSegmento.PRESENTES, presentes],
    [CorSegmento.FALTANTES, faltantes],
    [CorSegmento.CONFLITANTES, conflitantes],
  ];
  return (
    <Progress.Root w={LARGURA} size="sm">
      {total > 0 &&
        segmentos.map(([cor, n]) => (
          <Progress.Section key={cor} value={(n / total) * PERCENTUAL} color={cor} />
        ))}
    </Progress.Root>
  );
}
