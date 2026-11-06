import { Group, Progress, Stack, Text } from "@mantine/core";
import type { Progresso } from "../api/eventos";

const PERCENTUAL = 100;

export function ProgressoExecucao({ progresso }: { progresso: Progresso }) {
  const { fase, feito, total } = progresso;
  return (
    <Stack gap="xs" maw={560}>
      <Text>{fase}</Text>
      <Group wrap="nowrap">
        {total > 0 ? (
          <Progress value={(feito / total) * PERCENTUAL} flex={1} />
        ) : (
          <Progress value={PERCENTUAL} animated striped flex={1} />
        )}
        {total > 0 && (
          <Text c="dimmed" size="sm">
            {feito}/{total}
          </Text>
        )}
      </Group>
    </Stack>
  );
}
