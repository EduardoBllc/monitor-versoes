import { Alert, Badge, Button, Group, Loader, Paper, Stack, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type JSX } from "react";
import { consultaRepos, consultaVersoes } from "../api/cliente";
import { ModalCriar } from "../componentes/ModalCriar";
import { estaRodando } from "../execucoes";
import { Link } from "../navegacao";
import { useOperacoes } from "../operacoes/OperacoesProvider";
import { Pagina } from "../rotas";
import { FONTE_MONO } from "../tema";

export function PaginaRepo({ repo }: { repo: string }): JSX.Element {
  const operacoes = useOperacoes();
  const { retomar } = operacoes;
  const [criando, setCriando] = useState(false);
  const repos = useQuery(consultaRepos);
  const versoes = useQuery(consultaVersoes(repo));
  const caminho = repos.data?.find((r) => r.nome === repo)?.caminho;
  const ocupado = estaRodando(operacoes.execucoes, repo);
  const bloqueadas = operacoes.bloqueadas(repo);

  useEffect(() => {
    retomar(repo);
  }, [repo, retomar]);

  return (
    <Stack gap="md" maw={720}>
      <Group justify="space-between">
        <Title order={2}>{repo}</Title>
        <Button
          variant="light"
          color="orange"
          disabled={ocupado || caminho == null}
          onClick={() => setCriando(true)}
        >
          Nova versão
        </Button>
      </Group>
      {versoes.isLoading && <Loader />}
      {versoes.error && (
        <Alert color="red">
          {versoes.error.message}
          {caminho === null && " — o repositório está sem checkout local."}
        </Alert>
      )}
      <Stack gap={0}>
        {versoes.data?.map((v) => (
          <Paper key={v.numero} px="md" py="xs" radius={0}>
            <Group gap="sm">
              <Link
                para={{ pagina: Pagina.VERSAO, repo, versao: v.numero }}
                ff={FONTE_MONO}
                fw={600}
              >
                {v.numero}
              </Link>
              {v.liberada && <Badge variant="light" color="gray">liberada</Badge>}
              {bloqueadas.includes(v.numero) && (
                <Badge variant="light" color="red">bloqueada</Badge>
              )}
            </Group>
          </Paper>
        ))}
      </Stack>
      <ModalCriar
        repo={repo}
        existentes={versoes.data?.map((v) => v.numero) ?? []}
        aberto={criando}
        aoFechar={() => setCriando(false)}
        aoCriar={(numero) => operacoes.criar(repo, numero)}
      />
    </Stack>
  );
}
