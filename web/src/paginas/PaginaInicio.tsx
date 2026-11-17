import { Alert, Code, Group, Loader, Paper, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import type { JSX } from "react";
import { consultaRepos } from "../api/cliente";
import { Link } from "../navegacao";
import { Pagina } from "../rotas";

export function PaginaInicio(): JSX.Element {
  const repos = useQuery(consultaRepos);
  if (repos.isLoading) return <Loader />;
  if (repos.error) return <Alert color="red">{repos.error.message}</Alert>;
  if (repos.data?.length === 0)
    return (
      <Text c="dimmed">
        Nenhum repositório configurado. Crie uma seção{" "}
        <Code>[repos.&lt;nome&gt;]</Code> com o <Code>caminho</Code> do clone no{" "}
        <Code>config.toml</Code> central (README, “Configurar por projeto”).
      </Text>
    );
  return (
    <Stack gap="xs" maw={640}>
      {repos.data?.map((r) => (
        <Paper key={r.nome} px="md" py="xs">
          <Group gap="sm">
            {r.caminho === null ? (
              <>
                <Text role="link" aria-disabled="true" fw={600} c="dimmed">
                  {r.nome}
                </Text>
                <Text size="xs" c="dimmed">
                  indisponível — checkout local não encontrado
                </Text>
              </>
            ) : (
              <Link para={{ pagina: Pagina.REPO, repo: r.nome }} fw={600}>
                {r.nome}
              </Link>
            )}
          </Group>
        </Paper>
      ))}
    </Stack>
  );
}
