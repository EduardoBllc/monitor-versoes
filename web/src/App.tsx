import {
  Alert,
  AppShell,
  Button,
  Code,
  Loader,
  MantineProvider,
  Modal,
  Text,
} from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { CHAVE_REPOS, Metodo, api, ErroApi } from "./api/cliente";
import { EstadoExecucao, Operacao, TipoErro } from "./api/enums";
import {
  FaseAtualizacao,
  INICIAL,
  TipoEventoAtualizacao,
  acompanhaOcupado,
  proximo,
  type EstadoAtualizacao,
  type Evento,
  type EventoSimples,
} from "./atualizacao";
import { acompanhar, type Execucao } from "./api/eventos";
import type { RepoOption, VersionOption } from "./api/tipos";
import { Barra } from "./componentes/Barra";
import { Consulta } from "./componentes/Consulta";
import { ModalAbortar } from "./componentes/ModalAbortar";
import { ModalConfirmarLote } from "./componentes/ModalConfirmarLote";
import { ModalConfig } from "./componentes/ModalConfig";
import { ModalCriar } from "./componentes/ModalCriar";
import { ModalInscricoes } from "./componentes/ModalInscricoes";
import { ModalResultado } from "./componentes/ModalResultado";
import { PainelBloqueio } from "./componentes/PainelBloqueio";
import { ResultadoAtualizacao } from "./componentes/ResultadoAtualizacao";
import { Status } from "./componentes/Status";
import { notificarPendencia } from "./componentes/notificarPendencia";
import { notificarErro, notificarOk } from "./componentes/notificar";
import { ProgressoExecucao } from "./componentes/ProgressoExecucao";
import {
  PROGRESSO_INICIAL,
  SEM_EXECUCOES,
  TipoEfeito,
  avisoPendencia,
  concluir,
  estaRodando,
  iniciar,
  progredir,
  terminar,
  type EstadoExecucoes,
  type Resultado,
} from "./execucoes";
import { caminhoDe, lerCaminho } from "./rotas";

// Sem refetch ao voltar do editor nem retry: cada leitura de versões faz git fetch.
const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } },
});
const ALTURA_BARRA = 64;
const chave = (repo: string, versao: string): string => `${repo}@${versao}`;

function useCaminho() {
  const [caminho, setCaminho] = useState(() =>
    lerCaminho(window.location.pathname),
  );
  useEffect(() => {
    const ler = () => setCaminho(lerCaminho(window.location.pathname));
    window.addEventListener("popstate", ler);
    return () => window.removeEventListener("popstate", ler);
  }, []);
  const ir = useCallback((repo?: string, versao?: string, trocar = false) => {
    const destino = caminhoDe(repo, versao);
    if (trocar) window.history.replaceState(null, "", destino);
    else window.history.pushState(null, "", destino);
    setCaminho({ ...(repo && { repo }), ...(versao && { versao }) });
  }, []);
  return [caminho, ir] as const;
}

function Tela() {
  const cliente = useQueryClient();
  const [{ repo, versao }, ir] = useCaminho();
  const [execucoes, setExecucoes] = useState(SEM_EXECUCOES);
  const execRef = useRef(SEM_EXECUCOES);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [criando, setCriando] = useState(false);
  const [inscricoes, setInscricoes] = useState(false);
  const [configurando, setConfigurando] = useState(false);
  const [atualizacoes, setAtualizacoes] = useState<
    Readonly<Record<string, EstadoAtualizacao>>
  >({});
  const [abortando, setAbortando] = useState(false);
  const repoRef = useRef(repo);
  repoRef.current = repo;
  const versaoRef = useRef(versao);
  versaoRef.current = versao;
  const despachar = useCallback((k: string, ev: Evento) => {
    setAtualizacoes((a) => ({ ...a, [k]: proximo(a[k] ?? INICIAL, ev) }));
  }, []);
  // O ref é a fonte síncrona (evita duplo acompanhamento); o state só repinta.
  const mudar = useCallback((f: (e: EstadoExecucoes) => EstadoExecucoes) => {
    execRef.current = f(execRef.current);
    setExecucoes(execRef.current);
  }, []);

  const repos = useQuery({
    queryKey: CHAVE_REPOS,
    queryFn: () => api<RepoOption[]>(Metodo.GET, "/api/repos"),
  });
  const versoes = useQuery({
    queryKey: ["versoes", repo],
    queryFn: () =>
      api<VersionOption[]>(
        Metodo.GET,
        `/api/repos/${encodeURIComponent(repo ?? "")}/versoes`,
      ),
    enabled: repo !== undefined,
  });

  useEffect(() => {
    if (versoes.error) notificarErro(versoes.error);
  }, [versoes.error]);

  // Sem repo na URL, abre no primeiro com checkout; sem versão, na mais nova.
  useEffect(() => {
    if (repo === undefined) {
      const primeiro = repos.data?.find((r) => r.caminho !== null);
      if (primeiro) ir(primeiro.nome, undefined, true);
    } else if (versao === undefined && versoes.data?.[0]) {
      ir(repo, versoes.data[0].numero, true);
    }
  }, [repo, versao, repos.data, versoes.data, ir]);

  const seguir = useCallback(
    async (nome: string, versaoAlvo: string, auditar = false) => {
      const { estado, seguir: abrir } = iniciar(execRef.current, nome, auditar);
      if (!abrir) return;
      mudar(() => estado);
      try {
        const fim = await acompanhar(nome, (p) =>
          mudar((e) => progredir(e, nome, p)),
        );
        if (fim === null) {
          // Nada rodando mais: quem ficou em "aplicando" (409) volta ao que era.
          despachar(chave(nome, versaoAlvo), {
            tipo: TipoEventoAtualizacao.RECONECTOU,
            execucao: null,
          });
          return;
        }
        despachar(chave(fim.repo, fim.versao), {
          tipo: TipoEventoAtualizacao.TERMINOU,
          execucao: fim,
        });
        if (
          fim.operacao === Operacao.ABORTAR &&
          fim.estado !== EstadoExecucao.FALHOU
        )
          notificarOk("Atualização abortada");
        if (
          fim.operacao !== Operacao.VERIFICAR &&
          fim.operacao !== Operacao.CRIAR
        )
          void cliente.invalidateQueries({
            queryKey: ["chamados", fim.repo, fim.versao],
          });
        if (
          fim.operacao === Operacao.CRIAR &&
          fim.estado !== EstadoExecucao.FALHOU
        )
          void cliente.invalidateQueries({ queryKey: ["versoes", nome] });
        const efeito = concluir(
          execRef.current,
          fim,
          repoRef.current,
          versaoRef.current,
        );
        if (efeito?.tipo === TipoEfeito.ERRO)
          notificarErro(new ErroApi(efeito.tipoErro, efeito.mensagem, 0));
        else if (efeito?.tipo === TipoEfeito.RESULTADO)
          setResultado(efeito.resultado);
        else if (efeito?.tipo === TipoEfeito.NAVEGAR) {
          notificarOk(`Versão ${efeito.versao} criada`);
          ir(efeito.repo, efeito.versao);
        } else if (efeito?.tipo === TipoEfeito.AVISAR) {
          const destino = efeito.destino;
          if (destino)
            notificarPendencia(
              chave(destino.repo, destino.versao),
              efeito.mensagem,
              () => ir(destino.repo, destino.versao),
            );
          else notificarOk(efeito.mensagem);
        }
      } catch (erro) {
        notificarErro(erro);
        despachar(chave(nome, versaoAlvo), {
          tipo: TipoEventoAtualizacao.RECONECTOU,
          execucao: null,
        });
      } finally {
        mudar((e) => terminar(e, nome));
      }
    },
    [cliente, despachar, ir, mudar],
  );

  // Recarregar a página (ou abrir outra aba) retoma os picks abertos e a operação em curso.
  useEffect(() => {
    if (repo === undefined) return;
    const url = `/api/repos/${encodeURIComponent(repo)}`;
    void Promise.all([
      api<Execucao[]>(Metodo.GET, `${url}/pendencias`),
      api<Execucao | null>(Metodo.GET, `${url}/execucao`),
    ])
      .then(([pendencias, e]) => {
        // Pendências antes da atual: uma continuação rodando volta ao bloqueio se falhar.
        for (const x of [...pendencias, ...(e ? [e] : [])])
          despachar(chave(x.repo, x.versao), {
            tipo: TipoEventoAtualizacao.RECONECTOU,
            execucao: x,
          });
        for (const p of pendencias) {
          const aviso = avisoPendencia(p, versaoRef.current);
          if (aviso?.tipo === TipoEfeito.AVISAR && aviso.destino) {
            const { repo: r, versao: v } = aviso.destino;
            notificarPendencia(chave(r, v), aviso.mensagem, () => ir(r, v));
          }
        }
        if (e?.estado === EstadoExecucao.RODANDO) return seguir(repo, e.versao);
      })
      .catch(notificarErro);
  }, [repo, seguir, despachar, ir]);

  const disparar = async (caminho: string, corpo: unknown, auditar = false) => {
    if (repo === undefined || versao === undefined) return;
    const k = chave(repo, versao);
    try {
      await api<Execucao>(Metodo.POST, caminho, corpo);
    } catch (erro) {
      // 409: o repo está travado. Se for uma execução do daemon (outra aba), passa a
      // acompanhá-la; se for um processo de fora (CLI, TUI, inscrição), mostra a recusa.
      const ocupadoAqui =
        erro instanceof ErroApi &&
        erro.tipo === TipoErro.OCUPADO &&
        acompanhaOcupado(
          await api<Execucao | null>(
            Metodo.GET,
            `/api/repos/${encodeURIComponent(repo)}/execucao`,
          ).catch(() => null),
        );
      if (!ocupadoAqui) {
        notificarErro(erro);
        despachar(k, {
          tipo: TipoEventoAtualizacao.RECONECTOU,
          execucao: null,
        });
        return;
      }
      despachar(k, { tipo: TipoEventoAtualizacao.OCUPADO });
    }
    await seguir(repo, versao, auditar);
  };

  const base = `/api/repos/${encodeURIComponent(repo ?? "")}/versoes`;
  const ocupado = repo !== undefined && estaRodando(execucoes, repo);
  const chaveAtual =
    repo !== undefined && versao !== undefined ? chave(repo, versao) : "";
  const atualizacao = atualizacoes[chaveAtual] ?? INICIAL;
  const pendente =
    atualizacao.fase === FaseAtualizacao.BLOQUEADA ||
    atualizacao.fase === FaseAtualizacao.VAZIA;
  const disponivel = repos.data?.find((r) => r.nome === repo)?.caminho != null;
  const acaoAtualizacao = `${base}/${encodeURIComponent(versao ?? "")}/atualizacao`;
  const evento = (tipo: EventoSimples) => {
    if (chaveAtual !== "") despachar(chaveAtual, { tipo });
  };
  const bloqueadas = Object.entries(atualizacoes).flatMap(([k, a]) =>
    (a.fase === FaseAtualizacao.BLOQUEADA ||
      a.fase === FaseAtualizacao.VAZIA) &&
    repo !== undefined &&
    k.startsWith(`${repo}@`)
      ? [k.slice(repo.length + 1)]
      : [],
  );
  const aplicando =
    atualizacao.fase === FaseAtualizacao.PREVIA ||
    atualizacao.fase === FaseAtualizacao.APLICANDO;
  const previa = () => {
    evento(TipoEventoAtualizacao.INICIOU);
    void disparar(`${base}/${encodeURIComponent(versao ?? "")}/previa`, undefined);
  };
  const aplicar = (continuar: boolean) => {
    evento(
      continuar
        ? TipoEventoAtualizacao.CONTINUOU
        : TipoEventoAtualizacao.CONFIRMOU,
    );
    void disparar(
      continuar ? `${acaoAtualizacao}/continuar` : acaoAtualizacao,
      continuar
        ? { allow_empty: atualizacao.fase === FaseAtualizacao.VAZIA }
        : undefined,
    );
  };
  const cancelarLote = () => {
    evento(TipoEventoAtualizacao.CANCELOU);
    // Cancelar não desfaz a prévia (ela regravou o snapshot): a lista atrás está velha.
    void cliente.invalidateQueries({ queryKey: ["chamados", repo, versao] });
  };
  const abortar = () => {
    setAbortando(false);
    evento(TipoEventoAtualizacao.ABORTOU);
    void disparar(`${acaoAtualizacao}/abortar`, undefined);
  };
  const fecharResultado = () => {
    if (resultado)
      void cliente.invalidateQueries({
        queryKey: ["chamados", resultado.repo, resultado.versao],
      });
    setResultado(null);
  };

  return (
    <AppShell header={{ height: ALTURA_BARRA }} padding="md">
      <AppShell.Header>
        <Barra
          repos={repos.data ?? []}
          {...(repo && { repo })}
          versoes={versoes.data ?? []}
          {...(versao && { versao })}
          ocupado={ocupado}
          bloqueadas={bloqueadas}
          aoEscolherRepo={(nome) => ir(nome)}
          aoEscolherVersao={(numero) => repo && ir(repo, numero)}
          aoVerificar={(auditar) => {
            void disparar(
              `${base}/${encodeURIComponent(versao ?? "")}/verificacao`,
              { auditar },
              auditar,
            );
          }}
          slotAtualizar={
            pendente ? (
              <>
                <Button
                  color={
                    atualizacao.fase === FaseAtualizacao.VAZIA
                      ? "yellow"
                      : "red"
                  }
                  disabled={ocupado}
                  onClick={() => aplicar(true)}
                >
                  {atualizacao.fase === FaseAtualizacao.VAZIA
                    ? "Registrar vazio"
                    : "Continuar"}
                </Button>
                <Button
                  variant="light"
                  color="red"
                  disabled={ocupado}
                  onClick={() => setAbortando(true)}
                >
                  Abortar
                </Button>
              </>
            ) : (
              <Button
                color="orange"
                disabled={
                  ocupado || aplicando || !disponivel || versao === undefined
                }
                onClick={previa}
              >
                Atualizar
              </Button>
            )
          }
          aoCriar={() => setCriando(true)}
          aoInscricoes={() => setInscricoes(true)}
          aoConfigurar={() => setConfigurando(true)}
        />
      </AppShell.Header>
      <AppShell.Main>
        {repos.isLoading && <Loader />}
        {repos.error && <Alert color="red">{repos.error.message}</Alert>}
        {repos.data?.length === 0 && (
          <Text c="dimmed">
            Nenhum repositório configurado. Crie uma seção{" "}
            <Code>[repos.&lt;nome&gt;]</Code> com o <Code>caminho</Code> do clone no{" "}
            <Code>config.toml</Code> central (README, “Configurar por projeto”).
          </Text>
        )}
        {versoes.error && (
          <Alert color="red">
            {versoes.error.message}
            {repos.data?.find((r) => r.nome === repo)?.caminho === null &&
              " — o repositório está sem checkout local."}
          </Alert>
        )}
        {ocupado ? (
          <ProgressoExecucao
            progresso={execucoes.progresso[repo] ?? PROGRESSO_INICIAL}
          />
        ) : pendente && atualizacao.resultado ? (
          <PainelBloqueio resultado={atualizacao.resultado} />
        ) : (
          repo !== undefined &&
          versao !== undefined && (
            <Consulta key={`${repo}@${versao}`} repo={repo} versao={versao} />
          )
        )}
      </AppShell.Main>
      <ModalConfirmarLote
        status={
          atualizacao.fase === FaseAtualizacao.CONFIRMANDO
            ? atualizacao.status
            : null
        }
        versao={versao ?? ""}
        aoConfirmar={() => aplicar(false)}
        aoCancelar={cancelarLote}
      />
      <ModalAbortar
        aberto={abortando}
        aoConfirmar={abortar}
        aoFechar={() => setAbortando(false)}
      />
      <Modal
        opened={atualizacao.fase === FaseAtualizacao.CONCLUIDA}
        onClose={() => evento(TipoEventoAtualizacao.FECHOU)}
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
      <ModalResultado resultado={resultado} aoFechar={fecharResultado} />
      {repo !== undefined && (
        <ModalCriar
          repo={repo}
          existentes={versoes.data?.map((v) => v.numero) ?? []}
          aberto={criando}
          aoFechar={() => setCriando(false)}
          aoCriar={(numero) => void disparar(base, { numero })}
        />
      )}
      <ModalConfig
        aberto={configurando}
        aoFechar={() => setConfigurando(false)}
      />
      <ModalInscricoes
        aberto={inscricoes}
        aoFechar={() => setInscricoes(false)}
        {...(repo && { repo })}
        {...(versao && { versao })}
      />
    </AppShell>
  );
}

export function App() {
  return (
    <MantineProvider defaultColorScheme="auto">
      <QueryClientProvider client={queryClient}>
        <Notifications />
        <Tela />
      </QueryClientProvider>
    </MantineProvider>
  );
}
