import { Accordion, Alert, Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type JSX } from "react";
import { consultaRepos } from "../api/cliente";
import { ListaVersoes } from "../componentes/LinhaVersao";
import { ListaInscricoes } from "../componentes/ListaInscricoes";
import { ModalCriar } from "../componentes/ModalCriar";
import { estaRodando } from "../execucoes";
import { useOperacoes } from "../operacoes/OperacoesProvider";
import { emAberto, useVersoes } from "../versoes";

const LARGURA_MAXIMA = 900;
const ITEM_LIBERADAS = "liberadas";

export function PaginaRepo({ repo }: { repo: string }): JSX.Element {
  const operacoes = useOperacoes();
  const { retomar } = operacoes;
  const [criando, setCriando] = useState(false);
  const repos = useQuery(consultaRepos);
  const caminho = repos.data?.find((r) => r.nome === repo)?.caminho;
  // Repo fora da configuração (caminho undefined) consulta mesmo assim: a API responde o erro.
  const { versoes, buscando, erro } = useVersoes(
    repo,
    repos.data !== undefined && caminho !== null,
  );
  const ocupado = estaRodando(operacoes.execucoes, repo);
  const bloqueadas = operacoes.bloqueadas(repo);
  const abertas = versoes === undefined ? [] : emAberto(versoes);
  const liberadas = versoes?.filter((v) => v.liberada) ?? [];

  useEffect(() => {
    retomar(repo);
  }, [repo, retomar]);

  return (
    <Stack gap="md" maw={LARGURA_MAXIMA}>
      <Group justify="space-between">
        <Group gap="sm">
          <Title order={2}>{repo}</Title>
          {buscando && <Loader size="xs" />}
        </Group>
        <Button
          variant="light"
          color="orange"
          disabled={ocupado || caminho == null}
          onClick={() => setCriando(true)}
        >
          Nova versão
        </Button>
      </Group>
      {caminho === null && (
        <Text c="dimmed">indisponível — checkout local não encontrado</Text>
      )}
      {erro && <Alert color="red">{erro.message}</Alert>}
      {versoes?.length === 0 && caminho !== null && (
        <Text c="dimmed">nenhuma versão gravada</Text>
      )}
      <ListaVersoes repo={repo} versoes={abertas} bloqueadas={bloqueadas} />
      {liberadas.length > 0 && (
        <Accordion variant="contained">
          <Accordion.Item value={ITEM_LIBERADAS}>
            <Accordion.Control>{liberadas.length} versões liberadas</Accordion.Control>
            <Accordion.Panel>
              <ListaVersoes repo={repo} versoes={liberadas} bloqueadas={bloqueadas} />
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      )}
      <ListaInscricoes repo={repo} />
      <ModalCriar
        repo={repo}
        existentes={versoes?.map((v) => v.numero) ?? []}
        aberto={criando}
        aoFechar={() => setCriando(false)}
        aoCriar={(numero) => operacoes.criar(repo, numero)}
      />
    </Stack>
  );
}
