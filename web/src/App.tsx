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
import { Notifications, notifications } from "@mantine/notifications";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { CHAVE_REPOS, Metodo, api } from "./api/cliente";
import { AtualizarStatus } from "./api/enums";
import { FaseAtualizacao, INICIAL } from "./atualizacao";
import type { RepoOption, VersaoListada } from "./api/tipos";
import { Barra } from "./componentes/Barra";
import { Consulta } from "./componentes/Consulta";
import type { EstadoConflitoWeb } from "./componentes/EditorConflito";
import { ModalAbortar } from "./componentes/ModalAbortar";
import { ModalConfirmarLote } from "./componentes/ModalConfirmarLote";
import { ModalConfig } from "./componentes/ModalConfig";
import { ModalCriar } from "./componentes/ModalCriar";
import { ModalInscricoes } from "./componentes/ModalInscricoes";
import { ModalOrfaos } from "./componentes/ModalOrfaos";
import { ModalResultado } from "./componentes/ModalResultado";
import { PainelBloqueio } from "./componentes/PainelBloqueio";
import { ResultadoAtualizacao } from "./componentes/ResultadoAtualizacao";
import { Status } from "./componentes/Status";
import { notificarErro } from "./componentes/notificar";
import { ProgressoExecucao } from "./componentes/ProgressoExecucao";
import { PROGRESSO_INICIAL, estaRodando } from "./execucoes";
import { AVISO_DESCARTE } from "./conflito";
import {
  INTERVALO_CONSULTA_INSCRICOES_MS,
  consultaInscricoes,
  avisos,
} from "./inscricoes";
import type { InscricaoVista } from "./api/tipos";
import { useInstalacao } from "./instalacao";
import { chaveVersao } from "./operacoes/chave";
import { OperacoesProvider, useOperacoes } from "./operacoes/OperacoesProvider";
import { caminhoDe, lerCaminho } from "./rotas";

// Sem refetch ao voltar do editor nem retry: cada leitura de versões faz git fetch.
const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } },
});
const ALTURA_BARRA = 64;
// Lazy: o Monaco fica fora do chunk principal.
const EditorConflito = lazy(() => import("./componentes/EditorConflito"));
const CONFLITO_ABRINDO: EstadoConflitoWeb = { pendente: true, sujo: false };

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

function Tela({
  caminho: { repo, versao },
  ir,
}: {
  caminho: { repo?: string; versao?: string };
  ir: (repo?: string, versao?: string, trocar?: boolean) => void;
}) {
  const operacoes = useOperacoes();
  const { execucoes, resultado, retomar } = operacoes;
  const [criando, setCriando] = useState(false);
  const [inscricoes, setInscricoes] = useState(false);
  const [orfaos, setOrfaos] = useState(false);
  const [configurando, setConfigurando] = useState(false);
  const [abortando, setAbortando] = useState(false);
  const [resolvendo, setResolvendo] = useState<string | null>(null);
  const [conflitoWeb, setConflitoWeb] = useState(CONFLITO_ABRINDO);

  const instalacao = useInstalacao();
  const repos = useQuery({
    queryKey: CHAVE_REPOS,
    queryFn: () => api<RepoOption[]>(Metodo.GET, "/api/repos"),
  });
  const versoes = useQuery({
    queryKey: ["versoes", repo],
    queryFn: () =>
      api<VersaoListada[]>(
        Metodo.GET,
        `/api/repos/${encodeURIComponent(repo ?? "")}/versoes`,
      ),
    enabled: repo !== undefined,
  });

  useEffect(() => {
    if (versoes.error) notificarErro(versoes.error);
  }, [versoes.error]);

  const inscricoesVistas = useQuery({
    ...consultaInscricoes,
    refetchInterval: INTERVALO_CONSULTA_INSCRICOES_MS,
  });
  // Ref, não state: o efeito duplo do StrictMode não pode avisar a mesma mudança duas vezes.
  const inscricoesAnteriores = useRef<InscricaoVista[] | undefined>(undefined);
  useEffect(() => {
    const depois = inscricoesVistas.data;
    if (depois === undefined) return;
    for (const a of avisos(inscricoesAnteriores.current, depois))
      notifications.show({ title: a.titulo, message: a.mensagem, color: a.cor });
    inscricoesAnteriores.current = depois;
  }, [inscricoesVistas.data]);

  // Sem repo na URL, abre no primeiro com checkout; sem versão, na mais nova.
  useEffect(() => {
    if (repo === undefined) {
      const primeiro = repos.data?.find((r) => r.caminho !== null);
      if (primeiro) ir(primeiro.nome, undefined, true);
    } else if (versao === undefined && versoes.data?.[0]) {
      ir(repo, versoes.data[0].numero, true);
    }
  }, [repo, versao, repos.data, versoes.data, ir]);

  useEffect(() => {
    if (repo !== undefined) retomar(repo);
  }, [repo, retomar]);

  const ocupado = repo !== undefined && estaRodando(execucoes, repo);
  const chaveAtual =
    repo !== undefined && versao !== undefined ? chaveVersao(repo, versao) : "";
  const atualizacao =
    repo !== undefined && versao !== undefined
      ? operacoes.atualizacao(repo, versao)
      : INICIAL;
  const pendente =
    atualizacao.fase === FaseAtualizacao.BLOQUEADA ||
    atualizacao.fase === FaseAtualizacao.VAZIA;
  const disponivel = repos.data?.find((r) => r.nome === repo)?.caminho != null;
  const naVersao = (acao: (r: string, v: string) => void) => () => {
    if (repo !== undefined && versao !== undefined) acao(repo, versao);
  };
  const bloqueadas = repo === undefined ? [] : operacoes.bloqueadas(repo);
  // Bloqueio encerrado (continuou, abortou): o próximo passa de novo pelo painel.
  useEffect(() => {
    if (!pendente) setResolvendo(null);
  }, [pendente]);
  const naTelaConflito =
    resolvendo === chaveAtual &&
    pendente &&
    atualizacao.resultado?.status === AtualizarStatus.BLOCKED;
  // Só experiência de uso: quem decide o continuar é o motor.
  const continuarBarrado = naTelaConflito && conflitoWeb.pendente;
  const navegar = (acao: () => void) => {
    if (
      !(naTelaConflito && conflitoWeb.sujo) ||
      window.confirm(AVISO_DESCARTE)
    )
      acao();
  };
  const aplicando =
    atualizacao.fase === FaseAtualizacao.PREVIA ||
    atualizacao.fase === FaseAtualizacao.APLICANDO;
  const previa = naVersao(operacoes.previa);
  const continuar = naVersao((r, v) => operacoes.aplicar(r, v, true));
  const abortar = () => {
    setAbortando(false);
    naVersao(operacoes.abortar)();
  };

  return (
    <AppShell header={{ height: ALTURA_BARRA }} padding="md">
      <AppShell.Header>
        <Barra
          repos={repos.data ?? []}
          carregandoRepos={repos.isLoading}
          {...(repo && { repo })}
          versoes={versoes.data ?? []}
          carregandoVersoes={versoes.isLoading}
          {...(versao && { versao })}
          ocupado={ocupado}
          bloqueadas={bloqueadas}
          novidades={instalacao.data?.novidades ?? []}
          aoEscolherRepo={(nome) => navegar(() => ir(nome))}
          aoEscolherVersao={(numero) =>
            navegar(() => repo && ir(repo, numero))
          }
          aoVerificar={(auditar) =>
            naVersao((r, v) => operacoes.verificar(r, v, auditar))()
          }
          slotAtualizar={
            pendente ? (
              <>
                <Button
                  color={
                    atualizacao.fase === FaseAtualizacao.VAZIA
                      ? "yellow"
                      : "red"
                  }
                  disabled={ocupado || continuarBarrado}
                  onClick={continuar}
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
          aoOrfaos={() => setOrfaos(true)}
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
        ) : naTelaConflito && atualizacao.resultado && repo && versao ? (
          <Suspense fallback={<Loader />}>
            <EditorConflito
              repo={repo}
              versao={versao}
              resultado={atualizacao.resultado}
              aoSair={() => setResolvendo(null)}
              aoMudar={setConflitoWeb}
              aoContinuar={continuar}
            />
          </Suspense>
        ) : pendente && atualizacao.resultado ? (
          <PainelBloqueio
            resultado={atualizacao.resultado}
            aoResolver={() => {
              setConflitoWeb(CONFLITO_ABRINDO);
              setResolvendo(chaveAtual);
            }}
          />
        ) : (
          repo !== undefined &&
          versao !== undefined && (
            <Consulta key={chaveAtual} repo={repo} versao={versao} />
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
        aoConfirmar={naVersao((r, v) => operacoes.aplicar(r, v, false))}
        aoCancelar={naVersao(operacoes.cancelarLote)}
      />
      <ModalAbortar
        aberto={abortando}
        aoConfirmar={abortar}
        aoFechar={() => setAbortando(false)}
      />
      <Modal
        opened={atualizacao.fase === FaseAtualizacao.CONCLUIDA}
        onClose={naVersao(operacoes.fecharResultadoAtualizacao)}
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
      <ModalResultado resultado={resultado} aoFechar={operacoes.fecharResultado} />
      {repo !== undefined && (
        <ModalCriar
          repo={repo}
          existentes={versoes.data?.map((v) => v.numero) ?? []}
          aberto={criando}
          aoFechar={() => setCriando(false)}
          aoCriar={(numero) => operacoes.criar(repo, numero)}
        />
      )}
      {repo !== undefined && versao !== undefined && (
        <ModalOrfaos
          key={chaveAtual}
          repo={repo}
          versao={versao}
          aberto={orfaos}
          aoFechar={() => setOrfaos(false)}
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
  const [caminho, ir] = useCaminho();
  return (
    <MantineProvider defaultColorScheme="auto">
      <QueryClientProvider client={queryClient}>
        <Notifications />
        <OperacoesProvider aoNavegar={ir}>
          <Tela caminho={caminho} ir={ir} />
        </OperacoesProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
