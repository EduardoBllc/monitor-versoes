import { Alert, AppShell, Loader, MantineProvider, Text } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Metodo, api, ErroApi } from "./api/cliente";
import { EstadoExecucao, Operacao, TipoErro } from "./api/enums";
import { acompanhar, type Execucao, type Progresso } from "./api/eventos";
import type { RepoOption, VersionOption, VersionStatus } from "./api/tipos";
import { Barra } from "./componentes/Barra";
import { Consulta } from "./componentes/Consulta";
import { ModalCadastro } from "./componentes/ModalCadastro";
import { ModalCriar } from "./componentes/ModalCriar";
import { ModalInscricoes } from "./componentes/ModalInscricoes";
import { ModalResultado, type Resultado } from "./componentes/ModalResultado";
import { notificarErro, notificarOk } from "./componentes/notificar";
import { ProgressoExecucao } from "./componentes/ProgressoExecucao";
import { caminhoDe, lerCaminho } from "./rotas";

const queryClient = new QueryClient();
const ALTURA_BARRA = 64;
const INICIO: Progresso = { fase: "iniciando", feito: 0, total: 0 };

function useCaminho() {
  const [caminho, setCaminho] = useState(() => lerCaminho(window.location.pathname));
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
  const [execRepo, setExecRepo] = useState<string>();
  const [progresso, setProgresso] = useState(INICIO);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [criando, setCriando] = useState(false);
  const [cadastrando, setCadastrando] = useState(false);
  const [inscricoes, setInscricoes] = useState(false);
  const auditando = useRef(false);

  const repos = useQuery({
    queryKey: ["repos"],
    queryFn: () => api<RepoOption[]>(Metodo.GET, "/api/repos"),
  });
  const versoes = useQuery({
    queryKey: ["versoes", repo],
    queryFn: () => api<VersionOption[]>(Metodo.GET, `/api/repos/${encodeURIComponent(repo ?? "")}/versoes`),
    enabled: repo !== undefined,
  });

  // Sem repo na URL, abre no primeiro com checkout; sem versão, na mais nova.
  useEffect(() => {
    if (repo === undefined) {
      const primeiro = repos.data?.find((r) => r.caminho !== null);
      if (primeiro) ir(primeiro.nome, undefined, true);
    } else if (versao === undefined && versoes.data?.[0]) {
      ir(repo, versoes.data[0].numero, true);
    }
  }, [repo, versao, repos.data, versoes.data, ir]);

  const aoFim = useCallback(
    (nome: string, fim: Execucao | null) => {
      if (fim === null) return;
      if (fim.estado === EstadoExecucao.FALHOU) {
        notificarErro(new ErroApi(fim.erro?.tipo ?? TipoErro.INTERNO, fim.erro?.mensagem ?? "falhou", 0));
        return;
      }
      if (fim.operacao === Operacao.VERIFICAR) {
        setResultado({ status: fim.resultado as VersionStatus, auditado: auditando.current });
      } else if (fim.operacao === Operacao.CRIAR) {
        notificarOk(`Versão ${fim.versao} criada`);
        void cliente.invalidateQueries({ queryKey: ["versoes", nome] });
        ir(nome, fim.versao);
      }
    },
    [cliente, ir],
  );

  const seguir = useCallback(
    async (nome: string) => {
      setExecRepo(nome);
      setProgresso(INICIO);
      try {
        aoFim(nome, await acompanhar(nome, setProgresso));
      } catch (erro) {
        notificarErro(erro);
      } finally {
        setExecRepo((atual) => (atual === nome ? undefined : atual));
      }
    },
    [aoFim],
  );

  // Recarregar a página (ou abrir outra aba) durante uma operação passa a acompanhá-la.
  useEffect(() => {
    if (repo === undefined) return;
    void api<Execucao | null>(Metodo.GET, `/api/repos/${encodeURIComponent(repo)}/execucao`)
      .then((e) => {
        if (e?.estado === EstadoExecucao.RODANDO) return seguir(repo);
      })
      .catch(notificarErro);
  }, [repo, seguir]);

  const disparar = async (caminho: string, corpo: unknown) => {
    if (repo === undefined) return;
    try {
      await api<Execucao>(Metodo.POST, caminho, corpo);
    } catch (erro) {
      // 409: já há operação rodando neste repo (outra aba); passa a acompanhá-la.
      if (!(erro instanceof ErroApi && erro.tipo === TipoErro.OCUPADO)) {
        notificarErro(erro);
        return;
      }
    }
    await seguir(repo);
  };

  const base = `/api/repos/${encodeURIComponent(repo ?? "")}/versoes`;
  const ocupado = repo !== undefined && execRepo === repo;
  const fecharResultado = () => {
    setResultado(null);
    void cliente.invalidateQueries({ queryKey: ["chamados", repo, versao] });
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
          aoEscolherRepo={(nome) => ir(nome)}
          aoEscolherVersao={(numero) => repo && ir(repo, numero)}
          aoVerificar={(auditar) => {
            auditando.current = auditar;
            void disparar(`${base}/${encodeURIComponent(versao ?? "")}/verificacao`, { auditar });
          }}
          aoCriar={() => setCriando(true)}
          aoCadastrar={() => setCadastrando(true)}
          aoInscricoes={() => setInscricoes(true)}
        />
      </AppShell.Header>
      <AppShell.Main>
        {repos.isLoading && <Loader />}
        {repos.error && <Alert color="red">{repos.error.message}</Alert>}
        {repos.data?.length === 0 && (
          <Text c="dimmed">Nenhum repositório cadastrado. Use Cadastrar repo para começar.</Text>
        )}
        {ocupado ? (
          <ProgressoExecucao progresso={progresso} />
        ) : (
          repo !== undefined &&
          versao !== undefined && <Consulta key={`${repo}@${versao}`} repo={repo} versao={versao} />
        )}
      </AppShell.Main>
      <ModalResultado resultado={resultado} aoFechar={fecharResultado} />
      {repo !== undefined && (
        <ModalCriar
          repo={repo}
          aberto={criando}
          aoFechar={() => setCriando(false)}
          aoCriar={(numero) => void disparar(base, { numero })}
        />
      )}
      <ModalCadastro
        aberto={cadastrando}
        aoFechar={() => setCadastrando(false)}
        aoCadastrar={(nome) => {
          void cliente.invalidateQueries({ queryKey: ["repos"] });
          ir(nome);
        }}
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
