import { Alert, Box, Flex, Group, Loader, Modal, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useState, type JSX } from "react";
import { Metodo, api, consultaRepos } from "../api/cliente";
import { AtualizarStatus } from "../api/enums";
import { FaseAtualizacao } from "../atualizacao";
import { AcoesVersao } from "../componentes/AcoesVersao";
import { TEXTO_INDISPONIVEL } from "../componentes/LinhaVersao";
import type { EstadoConflitoWeb } from "../componentes/EditorConflito";
import { ModalAbortar } from "../componentes/ModalAbortar";
import { ModalConfirmarLote } from "../componentes/ModalConfirmarLote";
import { ModalOrfaos } from "../componentes/ModalOrfaos";
import { PainelBloqueio } from "../componentes/PainelBloqueio";
import { ProgressoExecucao } from "../componentes/ProgressoExecucao";
import { ResultadoAtualizacao } from "../componentes/ResultadoAtualizacao";
import { Status } from "../componentes/Status";
import { PROGRESSO_INICIAL, estaRodando } from "../execucoes";
import { consultaInscricoes } from "../inscricoes";
import { useGuardaDeSaida } from "../navegacao";
import { useOperacoes } from "../operacoes/OperacoesProvider";
import { FONTE_MONO } from "../tema";
import { chaveVerificacao, useVersoes } from "../versoes";
import type { VerificacaoGravada } from "../api/tipos";
import { Historico } from "./versao/Historico";
import { InscricaoDaVersao } from "./versao/InscricaoDaVersao";
import { ListaChamados } from "./versao/ListaChamados";
import { Veredito } from "./versao/Veredito";

// Lazy: o Monaco fica fora do chunk principal.
const EditorConflito = lazy(() => import("../componentes/EditorConflito"));
const CONFLITO_ABRINDO: EstadoConflitoWeb = { pendente: true, sujo: false };
const LARGURA_LATERAL = 280;

const consultaVerificacao = (repo: string, versao: string) => ({
  queryKey: chaveVerificacao(repo, versao),
  queryFn: () =>
    api<VerificacaoGravada | null>(
      Metodo.GET,
      `/api/repos/${encodeURIComponent(repo)}/versoes/${encodeURIComponent(versao)}/verificacao`,
    ),
});

export function PaginaVersao({
  repo,
  versao,
}: {
  repo: string;
  versao: string;
}): JSX.Element {
  const operacoes = useOperacoes();
  const { execucoes } = operacoes;
  const [orfaos, setOrfaos] = useState(false);
  const [abortando, setAbortando] = useState(false);
  const [resolvendo, setResolvendo] = useState(false);
  const [conflitoWeb, setConflitoWeb] = useState(CONFLITO_ABRINDO);
  const repos = useQuery(consultaRepos);
  const caminho = repos.data?.find((r) => r.nome === repo)?.caminho;
  // Repo fora da configuração (caminho undefined) consulta mesmo assim: a API responde o erro.
  const { versoes, buscando, erro } = useVersoes(
    repo,
    repos.data !== undefined && caminho !== null,
  );
  const verificacao = useQuery(consultaVerificacao(repo, versao));
  const inscricao = useQuery(consultaInscricoes).data?.find(
    (i) => i.repo === repo && i.versao === versao,
  );

  const ocupado = estaRodando(execucoes, repo);
  const atualizacao = operacoes.atualizacao(repo, versao);
  const pendente =
    atualizacao.fase === FaseAtualizacao.BLOQUEADA ||
    atualizacao.fase === FaseAtualizacao.VAZIA;
  // Bloqueio encerrado (continuou, abortou): o próximo passa de novo pelo painel.
  useEffect(() => {
    if (!pendente) setResolvendo(false);
  }, [pendente]);
  const naTelaConflito =
    resolvendo &&
    pendente &&
    atualizacao.resultado?.status === AtualizarStatus.BLOCKED;
  useGuardaDeSaida(naTelaConflito && conflitoWeb.sujo);
  const continuar = () => operacoes.aplicar(repo, versao, true);
  const listada = versoes?.find((v) => v.numero === versao);
  // Lista velha em recarga (versão recém-criada) não conta como ausência.
  const inexistente =
    versoes !== undefined && !buscando && erro === null && listada === undefined;

  if (caminho === null)
    return (
      <Stack gap="md">
        <Title order={1} size="h3" ff={FONTE_MONO}>
          {versao}
        </Title>
        <Text c="dimmed">{TEXTO_INDISPONIVEL}</Text>
      </Stack>
    );
  if (inexistente)
    return (
      <Stack gap="md">
        <Title order={1} size="h3" ff={FONTE_MONO}>
          {versao}
        </Title>
        <Alert color="red" title="Versão não encontrada">
          {repo} não tem a versão {versao}.
        </Alert>
      </Stack>
    );

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap">
        <Title order={1} size="h3" ff={FONTE_MONO}>
          {versao}
        </Title>
        <AcoesVersao
          fase={atualizacao.fase}
          liberada={listada?.liberada === true}
          disponivel={caminho != null}
          ocupado={ocupado}
          continuarBarrado={naTelaConflito && conflitoWeb.pendente}
          aoVerificar={(auditar) => operacoes.verificar(repo, versao, auditar)}
          aoAtualizar={() => operacoes.previa(repo, versao)}
          aoContinuar={continuar}
          aoAbortar={() => setAbortando(true)}
          aoOrfaos={() => setOrfaos(true)}
        />
      </Group>
      <Veredito gravada={verificacao.data} erro={verificacao.error} />
      <Flex align="flex-start" gap="md" direction={{ base: "column", sm: "row" }}>
        <Box w={{ base: "100%", sm: "auto" }} style={{ flex: 1, minWidth: 0 }}>
          {ocupado ? (
            <ProgressoExecucao
              progresso={execucoes.progresso[repo] ?? PROGRESSO_INICIAL}
            />
          ) : naTelaConflito && atualizacao.resultado ? (
            <Suspense fallback={<Loader />}>
              <EditorConflito
                repo={repo}
                versao={versao}
                resultado={atualizacao.resultado}
                aoSair={() => setResolvendo(false)}
                aoMudar={setConflitoWeb}
                aoContinuar={continuar}
              />
            </Suspense>
          ) : pendente && atualizacao.resultado ? (
            <PainelBloqueio
              resultado={atualizacao.resultado}
              aoResolver={() => {
                setConflitoWeb(CONFLITO_ABRINDO);
                setResolvendo(true);
              }}
            />
          ) : (
            <ListaChamados
              repo={repo}
              versao={versao}
              status={verificacao.data?.status ?? null}
            />
          )}
        </Box>
        {!naTelaConflito && (
          <Stack gap="sm" w={{ base: "100%", sm: LARGURA_LATERAL }} style={{ flexShrink: 0 }}>
            <InscricaoDaVersao repo={repo} versao={versao} />
            <Historico gravada={verificacao.data} inscricao={inscricao} />
          </Stack>
        )}
      </Flex>
      <ModalConfirmarLote
        status={
          atualizacao.fase === FaseAtualizacao.CONFIRMANDO
            ? atualizacao.status
            : null
        }
        versao={versao}
        aoConfirmar={() => operacoes.aplicar(repo, versao, false)}
        aoCancelar={() => operacoes.cancelarLote(repo, versao)}
      />
      <ModalAbortar
        aberto={abortando}
        aoConfirmar={() => {
          setAbortando(false);
          operacoes.abortar(repo, versao);
        }}
        aoFechar={() => setAbortando(false)}
      />
      <Modal
        opened={atualizacao.fase === FaseAtualizacao.CONCLUIDA}
        onClose={() => operacoes.fecharResultadoAtualizacao(repo, versao)}
        title="Atualização"
        size="xl"
      >
        {atualizacao.resultado ? (
          <ResultadoAtualizacao resultado={atualizacao.resultado} />
        ) : (
          atualizacao.status && (
            <Status status={atualizacao.status} auditado={false} />
          )
        )}
      </Modal>
      <ModalOrfaos
        repo={repo}
        versao={versao}
        aberto={orfaos}
        aoFechar={() => setOrfaos(false)}
      />
    </Stack>
  );
}
