import { Group, Loader, Modal, Stack, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useState, type JSX } from "react";
import { consultaRepos, consultaVersoes } from "../api/cliente";
import { AtualizarStatus } from "../api/enums";
import { FaseAtualizacao } from "../atualizacao";
import { AcoesVersao } from "../componentes/AcoesVersao";
import { Consulta } from "../componentes/Consulta";
import type { EstadoConflitoWeb } from "../componentes/EditorConflito";
import { ModalAbortar } from "../componentes/ModalAbortar";
import { ModalConfirmarLote } from "../componentes/ModalConfirmarLote";
import { ModalInscricoes } from "../componentes/ModalInscricoes";
import { ModalOrfaos } from "../componentes/ModalOrfaos";
import { PainelBloqueio } from "../componentes/PainelBloqueio";
import { ProgressoExecucao } from "../componentes/ProgressoExecucao";
import { ResultadoAtualizacao } from "../componentes/ResultadoAtualizacao";
import { Status } from "../componentes/Status";
import { PROGRESSO_INICIAL, estaRodando } from "../execucoes";
import { useGuardaDeSaida } from "../navegacao";
import { useOperacoes } from "../operacoes/OperacoesProvider";
import { FONTE_MONO } from "../tema";

// Lazy: o Monaco fica fora do chunk principal.
const EditorConflito = lazy(() => import("../componentes/EditorConflito"));
const CONFLITO_ABRINDO: EstadoConflitoWeb = { pendente: true, sujo: false };

export function PaginaVersao({
  repo,
  versao,
}: {
  repo: string;
  versao: string;
}): JSX.Element {
  const operacoes = useOperacoes();
  const { execucoes, retomar } = operacoes;
  const [inscricoes, setInscricoes] = useState(false);
  const [orfaos, setOrfaos] = useState(false);
  const [abortando, setAbortando] = useState(false);
  const [resolvendo, setResolvendo] = useState(false);
  const [conflitoWeb, setConflitoWeb] = useState(CONFLITO_ABRINDO);
  const repos = useQuery(consultaRepos);
  const versoes = useQuery(consultaVersoes(repo));

  useEffect(() => {
    retomar(repo);
  }, [repo, retomar]);

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

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap">
        <Title order={1} size="h3" ff={FONTE_MONO}>
          {versao}
        </Title>
        <AcoesVersao
          fase={atualizacao.fase}
          liberada={versoes.data?.find((v) => v.numero === versao)?.liberada === true}
          disponivel={repos.data?.find((r) => r.nome === repo)?.caminho != null}
          ocupado={ocupado}
          continuarBarrado={naTelaConflito && conflitoWeb.pendente}
          aoVerificar={(auditar) => operacoes.verificar(repo, versao, auditar)}
          aoAtualizar={() => operacoes.previa(repo, versao)}
          aoContinuar={continuar}
          aoAbortar={() => setAbortando(true)}
          aoOrfaos={() => setOrfaos(true)}
          aoInscricoes={() => setInscricoes(true)}
        />
      </Group>
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
        <Consulta repo={repo} versao={versao} />
      )}
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
      <ModalInscricoes
        aberto={inscricoes}
        aoFechar={() => setInscricoes(false)}
        repo={repo}
        versao={versao}
      />
    </Stack>
  );
}
