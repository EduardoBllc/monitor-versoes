import { Alert, Code, CopyButton, Button, Group, Stack, Text } from "@mantine/core";
import { AtualizarStatus } from "../api/enums";
import type { AtualizarResult } from "../api/tipos";
import { ResultadoAtualizacao } from "./ResultadoAtualizacao";

const TAMANHO_HASH = 8;

export function PainelBloqueio({ resultado }: { resultado: AtualizarResult }) {
  const bloqueada = resultado.status === AtualizarStatus.BLOCKED;
  return (
    <Stack maw={720}>
      <Text fw={700} c={bloqueada ? "red" : "yellow"}>
        {bloqueada ? "● Atualização bloqueada" : "● Resolução sem alteração"}
      </Text>
      <ResultadoAtualizacao resultado={resultado} />
      <Text>
        Commit: <Code>{resultado.blocked_commit.slice(0, TAMANHO_HASH)}</Code>
      </Text>
      {bloqueada && (
        <>
          <div>
            <Text>Arquivos em conflito:</Text>
            {(resultado.arquivos_conflito ?? []).map((a) => (
              <Code key={a} block>
                {a}
              </Code>
            ))}
          </div>
          {(resultado.culpados ?? []).length > 0 && (
            <Text>
              Depende de: {(resultado.culpados ?? []).map((c) => `#${c}`).join(", ")}
            </Text>
          )}
        </>
      )}
      <Group gap="xs">
        <Text>Worktree:</Text>
        <Code>{resultado.worktree}</Code>
        <CopyButton value={resultado.worktree}>
          {({ copied, copy }) => (
            <Button size="compact-xs" variant="default" onClick={copy}>
              {copied ? "Copiado" : "Copiar"}
            </Button>
          )}
        </CopyButton>
      </Group>
      <Alert color="yellow">
        {bloqueada
          ? "Resolva os arquivos na worktree com o seu editor e então clique em Continuar, ou descarte em Abortar."
          : "A resolução não deixou alteração nenhuma no alvo. Registrar vazio entra com um commit vazio, com o trailer -x; Abortar descarta o commit."}
      </Alert>
    </Stack>
  );
}
