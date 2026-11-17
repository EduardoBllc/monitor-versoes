import { Alert, Code, Flex, Group, Loader, Paper, Stack, Text } from "@mantine/core";
import { useQueries, useQuery } from "@tanstack/react-query";
import type { JSX } from "react";
import { Metodo, api, consultaRepos } from "../api/cliente";
import { EstadoExecucao } from "../api/enums";
import type { Execucao } from "../api/eventos";
import type { RepoOption } from "../api/tipos";
import {
  ListaVersoes,
  TEXTO_INDISPONIVEL,
  TEXTO_NENHUMA_GRAVADA,
} from "../componentes/LinhaVersao";
import { ListaInscricoes } from "../componentes/ListaInscricoes";
import {
  INTERVALO_EXECUCAO_MS,
  PrecisaDeVoce,
  consultaPendencias,
} from "../componentes/PrecisaDeVoce";
import { Link } from "../navegacao";
import { useOperacoes } from "../operacoes/OperacoesProvider";
import { Pagina } from "../rotas";
import { FONTE_MONO } from "../tema";
import { emAberto, useVersoes } from "../versoes";

const LARGURA_LATERAL = 290;
const CHAVE_EXECUCAO = "execucao";

function RepoNaInicio({ repo }: { repo: RepoOption }): JSX.Element {
  const disponivel = repo.caminho !== null;
  const { versoes, buscando, erro } = useVersoes(repo.nome, disponivel);
  // As do daemon cobrem a home recarregada; as do provider, o que esta aba acabou de fazer.
  const doDaemon = useQuery({ ...consultaPendencias(repo.nome), enabled: disponivel }).data;
  const bloqueadas = [
    ...useOperacoes().bloqueadas(repo.nome),
    ...(doDaemon ?? []).map((p) => p.versao),
  ];
  const abertas = versoes === undefined ? undefined : emAberto(versoes);
  return (
    <Paper component="section" aria-label={repo.nome}>
      <Group gap="sm" px="md" py="xs">
        {disponivel ? (
          <Link para={{ pagina: Pagina.REPO, repo: repo.nome }} fw={600}>
            {repo.nome}
          </Link>
        ) : (
          <Text role="link" aria-disabled="true" fw={600} c="dimmed">
            {repo.nome}
          </Text>
        )}
        <Text size="xs" c="dimmed">
          {!disponivel
            ? TEXTO_INDISPONIVEL
            : versoes?.length === 0
              ? TEXTO_NENHUMA_GRAVADA
              : abertas !== undefined && `${abertas.length} em aberto`}
        </Text>
        {buscando && <Loader size="xs" />}
      </Group>
      {erro && (
        <Text size="xs" c="red" px="md" pb="xs">
          {erro.message}
        </Text>
      )}
      {abertas !== undefined && (
        <ListaVersoes repo={repo.nome} versoes={abertas} bloqueadas={bloqueadas} />
      )}
    </Paper>
  );
}

// O provider só acompanha o que esta aba disparou ou retomou: a home pergunta a cada repo.
function EmCurso({ repos }: { repos: string[] }): JSX.Element | null {
  const rodando = useQueries({
    queries: repos.map((repo) => ({
      queryKey: [CHAVE_EXECUCAO, repo],
      queryFn: () =>
        api<Execucao | null>(Metodo.GET, `/api/repos/${encodeURIComponent(repo)}/execucao`),
      refetchInterval: INTERVALO_EXECUCAO_MS,
    })),
    combine: (rs) => rs.flatMap((r) => (r.data?.estado === EstadoExecucao.RODANDO ? [r.data] : [])),
  });
  if (rodando.length === 0) return null;
  return (
    <Paper px="md" py="sm">
      {rodando.map((e) => (
        <Text key={e.id} size="sm">
          ▶ {e.operacao} {e.repo}{" "}
          <Text span inherit ff={FONTE_MONO}>
            {e.versao}
          </Text>
          {e.progresso && (
            <Text span size="xs" c="dimmed">
              {" "}
              · {e.progresso.fase}
            </Text>
          )}
        </Text>
      ))}
    </Paper>
  );
}

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
  const todos = repos.data ?? [];
  const disponiveis = todos.filter((r) => r.caminho !== null).map((r) => r.nome);
  return (
    <Stack gap="md">
      <PrecisaDeVoce repos={disponiveis} />
      <Flex align="flex-start" gap="md" direction={{ base: "column", md: "row" }}>
        <Stack gap="md" w={{ base: "100%", md: "auto" }} style={{ flex: 1, minWidth: 0 }}>
          {todos.map((r) => (
            <RepoNaInicio key={r.nome} repo={r} />
          ))}
        </Stack>
        <Stack gap="md" w={{ base: "100%", md: LARGURA_LATERAL }} style={{ flexShrink: 0 }}>
          <EmCurso repos={disponiveis} />
          <ListaInscricoes />
        </Stack>
      </Flex>
    </Stack>
  );
}
