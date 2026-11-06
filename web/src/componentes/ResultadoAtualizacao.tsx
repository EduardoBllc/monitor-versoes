import { Alert, Code, Stack, Text } from "@mantine/core";
import type { AtualizarResult, CommitRef } from "../api/tipos";

const TAMANHO_HASH = 8;
const hash = (h: string): string => h.slice(0, TAMANHO_HASH);

export function ResultadoAtualizacao({
  resultado,
}: {
  resultado: AtualizarResult;
}) {
  const aplicados = resultado.aplicados ?? [];
  const vazios = resultado.vazios ?? [];
  const porChamado = new Map<string, CommitRef[]>();
  for (const c of aplicados)
    porChamado.set(c.chamado, [...(porChamado.get(c.chamado) ?? []), c]);
  const alertas = [
    resultado.status_versao?.tasks_ambiguas?.length
      ? `Chamados em mais de uma versão: ${resultado.status_versao.tasks_ambiguas.join(", ")}`
      : null,
    resultado.status_versao?.tasks_sem_commits?.length
      ? `Chamados sem commits: ${resultado.status_versao.tasks_sem_commits.join(", ")}`
      : null,
    resultado.status_versao && !resultado.status_versao.estado_integro
      ? `Estado divergente do git: ${(resultado.status_versao.commits_sumidos ?? []).map(hash).join(", ")}`
      : null,
  ].filter((a) => a !== null);
  return (
    <Stack gap="xs">
      {[...porChamado].map(([chamado, itens]) => (
        <Text key={chamado}>
          #{chamado} · {itens.length} commit{itens.length === 1 ? "" : "s"}:{" "}
          {itens.map((c) => (
            <Code key={c.hash_origem} mr={4}>
              {hash(c.hash_origem)}
            </Code>
          ))}
        </Text>
      ))}
      {aplicados.length === 0 && resultado.blocked_commit === "" && (
        <Text c="dimmed">Branch já estava atualizada.</Text>
      )}
      {vazios.length > 0 && (
        <Text c="yellow">
          {vazios.length} commits sem alteração no alvo, registrados como commit
          vazio: {vazios.map((c) => hash(c.hash_origem)).join(", ")}
        </Text>
      )}
      {resultado.ja_presentes > 0 && (
        <Text c="dimmed">
          {resultado.ja_presentes} commits já presentes no histórico.
        </Text>
      )}
      {alertas.length > 0 && (
        <Alert color="yellow">
          {alertas.map((a) => (
            <div key={a}>{a}</div>
          ))}
        </Alert>
      )}
    </Stack>
  );
}
