import { Code, Text } from "@mantine/core";
import type { NovidadeVista } from "../api/tipos";

// Uma linha só: o cabeçalho tem altura fixa; o resto fica no title do "+N".
export function AvisoVersao({ novidades }: { novidades: NovidadeVista[] }) {
  const [primeira, ...resto] = novidades;
  if (primeira === undefined) return null;
  return (
    <Text size="xs" c="orange">
      {primeira.texto} <Code>{primeira.comando}</Code>
      {resto.length > 0 && (
        <Text span inherit title={resto.map((n) => `${n.texto} ${n.comando}`).join("\n")}>
          {` +${resto.length}`}
        </Text>
      )}
    </Text>
  );
}
