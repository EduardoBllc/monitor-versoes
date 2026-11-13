import {
  Alert,
  Badge,
  Button,
  Code,
  CopyButton,
  Grid,
  Group,
  Modal,
  NavLink,
  Stack,
  Text,
  useComputedColorScheme,
} from "@mantine/core";
import { DiffEditor, Editor, loader } from "@monaco-editor/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as monaco from "monaco-editor";
import TrabalhadorEditor from "monaco-editor/editor/editor.worker?worker";
import TrabalhadorJson from "monaco-editor/language/json/json.worker?worker";
import { useEffect, useRef, useState } from "react";
import { ErroApi, Metodo, api } from "../api/cliente";
import { TipoArquivo, TipoErro, assertNever } from "../api/enums";
import type {
  ArquivoDoConflito,
  AtualizarResult,
  ConflitoAberto,
  ConteudoDoConflito,
  PedidoProposta,
  PropostaDeBloco,
  Resolucao,
} from "../api/tipos";
import {
  AVISO_DESCARTE,
  type EstadoBloco,
  Lado,
  proximoPendente,
  temMarcadores,
} from "../conflito";
import { linguagemDe } from "../linguagem";
import {
  type EstadoPropostas,
  SEM_PROPOSTAS,
  descartar,
  falhar,
  iniciar,
  invalidar,
  mostraGatilhos,
  podar,
  receber,
  vigente,
} from "../proposta";
import { MergeConteudo } from "./MergeConteudo";
import { SO_LEITURA } from "./monacoConflito";
import { ModalReabrir } from "./ModalReabrir";
import { notificarErro, notificarOk } from "./notificar";
import { TAMANHO_HASH } from "./PainelBloqueio";

// Monaco do bundle e workers locais, sem CDN: o daemon só serve 127.0.0.1.
self.MonacoEnvironment = {
  getWorker: (_id: string, rotulo: string) =>
    rotulo === "json" ? new TrabalhadorJson() : new TrabalhadorEditor(),
};
// Marcador de conflito não é JSON válido: o sublinhado vermelho seria ruído.
monaco.json.jsonDefaults.setDiagnosticsOptions({ validate: false });
loader.config({ monaco });

const ALTURA = "60vh";
const COLUNA_LISTA = 3;
const COLUNA_CONTEUDO = 9;

enum Tema {
  CLARO = "light",
  ESCURO = "vs-dark",
}

enum RotaConflito {
  RESOLUCAO = "resolucao",
  REABERTURA = "reabertura",
  PROPOSTA = "proposta",
}

// Cada painel tem o próprio modelo no Monaco; o commit no caminho impede reuso entre picks.
enum Painel {
  THEIRS = "theirs",
  OURS = "ours",
  RESULTADO = "resultado",
  BASE = "base",
  MODIFICADO = "modificado",
  VER_BASE = "ver-base",
}

enum EsquemaCor {
  ESCURO = "dark",
}


export type EstadoConflitoWeb = { pendente: boolean; sujo: boolean };

type Edicao = { texto: string; versao: string };

function rotuloTipo(tipo: TipoArquivo): string {
  switch (tipo) {
    case TipoArquivo.CONTEUDO:
      return "conteúdo";
    case TipoArquivo.MODIFICADO_APAGADO:
      return "modificado/apagado";
    case TipoArquivo.OUTRO:
      return "outro";
    default:
      return assertNever(tipo);
  }
}

export default function EditorConflito({
  repo,
  versao,
  resultado,
  aoSair,
  aoMudar,
  aoContinuar,
}: {
  repo: string;
  versao: string;
  resultado: AtualizarResult;
  aoSair: () => void;
  aoMudar: (estado: EstadoConflitoWeb) => void;
  aoContinuar: () => void;
}) {
  const cliente = useQueryClient();
  const tema =
    useComputedColorScheme() === EsquemaCor.ESCURO ? Tema.ESCURO : Tema.CLARO;
  const url = `/api/repos/${encodeURIComponent(repo)}/versoes/${encodeURIComponent(versao)}/conflito`;
  const chave = ["conflito", repo, versao];
  // Volta ao foco relê a lista: o editor local pode ter resolvido algo.
  const conflito = useQuery({
    queryKey: chave,
    queryFn: () => api<ConflitoAberto>(Metodo.GET, url),
    refetchOnWindowFocus: true,
    // Sem cache entre aberturas: depois do Continuar o pick é outro.
    gcTime: 0,
  });
  const arquivos = conflito.data?.arquivos ?? [];
  const [escolhido, setEscolhido] = useState<string | null>(null);
  const atual: ArquivoDoConflito | undefined =
    arquivos.find((a) => a.caminho === escolhido) ??
    arquivos.find((a) => !a.resolvido) ??
    arquivos[0];
  const conteudo = useQuery({
    // O commit na chave: novo pick no mesmo caminho é outra leitura.
    queryKey: [...chave, conflito.data?.commit, atual?.caminho],
    queryFn: () =>
      api<ConteudoDoConflito>(
        Metodo.GET,
        `${url}/arquivo?caminho=${encodeURIComponent(atual?.caminho ?? "")}`,
      ),
    enabled: atual !== undefined,
    gcTime: 0,
  });
  const dados = conteudo.data;
  const [edicao, setEdicao] = useState<Edicao | null>(null);
  const [confirmar, setConfirmar] = useState<(() => void) | null>(null);
  const [reabrindo, setReabrindo] = useState<string | null>(null);
  const [desatualizado, setDesatualizado] = useState(false);
  const [verBase, setVerBase] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [propostas, setPropostas] = useState(SEM_PROPOSTAS);
  // O ref é a fonte da verdade, atualizado na hora: dois cliques antes do
  // render seguinte não partem do mesmo retrato, e o catch vê a geração atual.
  const propostasAtuais = useRef(propostas);
  const mudarPropostas = (f: (e: EstadoPropostas) => EstadoPropostas) => {
    propostasAtuais.current = f(propostasAtuais.current);
    setPropostas(propostasAtuais.current);
  };
  // Os blocos ficam no estado (o botão re-renderiza) e num ref, que a
  // resposta assíncrona lê sem pegar a versão da hora do pedido.
  const [estados, setEstados] = useState<EstadoBloco[]>([]);
  const estadosAtuais = useRef(estados);
  const mudarEstados = (novos: EstadoBloco[]) => {
    estadosAtuais.current = novos;
    setEstados(novos);
    mudarPropostas((e) => podar(e, novos));
  };
  const id = `${conflito.data?.commit ?? ""}/${atual?.caminho ?? ""}`;
  // Nova leitura do disco (resolver, reabrir, recarregar) recomeça a tela.
  const chaveMerge =
    atual && dados ? `${id}/${dados.versao_disco}/${atual.resolvido}` : "";

  const texto = edicao?.texto ?? dados?.disco ?? "";
  const linguagem = linguagemDe(
    atual?.caminho ?? "",
    monaco.languages.getLanguages(),
  );
  const sujo = edicao !== null && edicao.texto !== dados?.disco;
  // OUTRO só se resolve fora da web; quem barra o Continuar nesse caso é o motor.
  const pendente = arquivos.some(
    (a) => !a.resolvido && a.tipo !== TipoArquivo.OUTRO,
  );

  useEffect(() => aoMudar({ pendente, sujo }), [pendente, sujo, aoMudar]);

  // Sem estados até o editor novo montar: o botão não pede as ordens do anterior.
  useEffect(() => {
    mudarPropostas(invalidar);
    mudarEstados([]);
  }, [chaveMerge]);

  useEffect(() => {
    if (!sujo) return;
    const avisar = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [sujo]);

  const tratar = (erro: unknown) => {
    if (erro instanceof ErroApi && erro.tipo === TipoErro.DESATUALIZADO) {
      setDesatualizado(true);
      return;
    }
    notificarErro(erro);
    // Sem pick pendente (fechado em outro lugar): volta ao painel de bloqueio.
    if (erro instanceof ErroApi && erro.tipo === TipoErro.NAO_ENCONTRADO)
      aoSair();
  };

  useEffect(() => {
    if (conflito.error) tratar(conflito.error);
  }, [conflito.error]);
  useEffect(() => {
    if (conteudo.error) tratar(conteudo.error);
  }, [conteudo.error]);

  const descartando = (acao: () => void) => () => {
    setEdicao(null);
    mudarPropostas(invalidar);
    setDesatualizado(false);
    acao();
  };
  const guardar = (acao: () => void) => {
    if (sujo) setConfirmar(() => descartando(acao));
    else descartando(acao)();
  };

  const enviar = async (rota: RotaConflito, corpo: unknown) => {
    setEnviando(true);
    try {
      await api<void>(Metodo.POST, `${url}/${rota}`, corpo);
      return true;
    } catch (erro) {
      tratar(erro);
      return false;
    } finally {
      setEnviando(false);
      void cliente.invalidateQueries({ queryKey: chave });
    }
  };

  const resolver = async (novo: string | null) => {
    if (!atual || !dados) return;
    const corpo: Resolucao = {
      caminho: atual.caminho,
      conteudo: novo,
      versao_disco: edicao?.versao ?? dados.versao_disco,
    };
    if (await enviar(RotaConflito.RESOLUCAO, corpo)) {
      setEdicao(null);
      notificarOk(`${atual.caminho} resolvido`);
      // Lista relida: escolher sobre a velha avançaria para o que acabou de resolver.
      const relida = await conflito.refetch();
      if (relida.isError || !relida.data) return;
      const proximo = proximoPendente(relida.data.arquivos, atual.caminho);
      if (proximo === null) aoContinuar();
      else setEscolhido(proximo);
    }
  };

  const reabrir = async () => {
    const caminho = reabrindo;
    setReabrindo(null);
    if (caminho !== null) await enviar(RotaConflito.REABERTURA, { caminho });
  };

  const pedir = async (alvo: number | null) => {
    if (!atual || !dados) return;
    const inicio = iniciar(
      propostasAtuais.current,
      estadosAtuais.current,
      alvo,
    );
    if (inicio === null) return;
    mudarPropostas(() => inicio.estado);
    const corpo: PedidoProposta = {
      caminho: atual.caminho,
      versao_disco: edicao?.versao ?? dados.versao_disco,
      ordens: inicio.ordens,
    };
    try {
      const recebidas = await api<PropostaDeBloco[]>(
        Metodo.POST,
        `${url}/${RotaConflito.PROPOSTA}`,
        corpo,
      );
      mudarPropostas((e) =>
        receber(e, inicio.geracao, recebidas, estadosAtuais.current),
      );
    } catch (erro) {
      mudarPropostas((e) => falhar(e, inicio.geracao));
      // Resposta de outro arquivo ou leitura: o erro já não é desta tela.
      if (vigente(propostasAtuais.current, inicio.geracao)) tratar(erro);
    }
  };

  const editar = (novo: string) => {
    if (!atual || !dados || novo === texto) return;
    // Fixa o arquivo: a lista relida no foco não troca o buffer de dono.
    setEscolhido(atual.caminho);
    setEdicao({ texto: novo, versao: edicao?.versao ?? dados.versao_disco });
  };

  const corpo = () => {
    if (!atual || !dados) return null;
    // O esquema gerado tipa como união de strings; o cast alinha ao enum do switch.
    const tipo = dados.tipo as TipoArquivo;
    const gatilhos = mostraGatilhos(
      conflito.data?.sugestao_disponivel ?? false,
      tipo,
      atual.resolvido,
    );
    const modelo = (painel: Painel) => `${painel}/${id}`;
    const botaoReabrir = (
      <Button
        variant="light"
        disabled={enviando}
        onClick={() => setReabrindo(atual.caminho)}
      >
        Reabrir
      </Button>
    );
    switch (tipo) {
      case TipoArquivo.CONTEUDO:
        return (
          <Stack>
            <MergeConteudo
              key={chaveMerge}
              linguagem={linguagem}
              modelos={{
                [Lado.THEIRS]: modelo(Painel.THEIRS),
                [Lado.OURS]: modelo(Painel.OURS),
                resultado: modelo(Painel.RESULTADO),
              }}
              dados={dados}
              texto={texto}
              resolvido={atual.resolvido}
              tema={tema}
              aoMudar={editar}
              gatilhos={gatilhos}
              propostas={propostas}
              aoSugerir={(k) => void pedir(k)}
              aoDescartarProposta={(k) => mudarPropostas((e) => descartar(e, k))}
              aoMudarEstados={mudarEstados}
            />
            <Group>
              {atual.resolvido ? (
                botaoReabrir
              ) : (
                <Button
                  disabled={enviando || temMarcadores(texto)}
                  onClick={() => void resolver(texto)}
                >
                  Marcar resolvido
                </Button>
              )}
              {dados.base !== null && (
                <Button variant="default" onClick={() => setVerBase(true)}>
                  Ver base
                </Button>
              )}
              {gatilhos && (
                <Button
                  variant="default"
                  leftSection={<span className="codicon codicon-sparkle" />}
                  disabled={iniciar(propostas, estados, null) === null}
                  onClick={() => void pedir(null)}
                >
                  Sugerir blocos abertos
                </Button>
              )}
              {!atual.resolvido && temMarcadores(texto) && (
                <Text size="sm" c="dimmed">
                  Ainda há marcadores de conflito no resultado.
                </Text>
              )}
            </Group>
          </Stack>
        );
      case TipoArquivo.MODIFICADO_APAGADO: {
        const existente = dados.ours ?? dados.theirs;
        return (
          <Stack>
            <Text>
              {dados.ours === null
                ? "O alvo (ours) apagou o arquivo e o commit aplicado (theirs) o modificou."
                : "O commit aplicado (theirs) apagou o arquivo e o alvo (ours) o modificou."}{" "}
              À esquerda a base, à direita o lado modificado.
            </Text>
            {/* A lib descarta os modelos antes do editor e o Monaco lança erro; aqui é depois. */}
            <DiffEditor
              key={id}
              keepCurrentOriginalModel
              keepCurrentModifiedModel
              onMount={(editor) => {
                const modelos = editor.getModel();
                editor.onDidDispose(() => {
                  modelos?.original.dispose();
                  modelos?.modified.dispose();
                });
              }}
              height={ALTURA}
              language={linguagem}
              original={dados.base ?? ""}
              modified={existente ?? ""}
              originalModelPath={modelo(Painel.BASE)}
              modifiedModelPath={modelo(Painel.MODIFICADO)}
              theme={tema}
              options={SO_LEITURA}
            />
            <Group>
              {atual.resolvido ? (
                botaoReabrir
              ) : (
                <>
                  <Button
                    disabled={enviando}
                    onClick={() => void resolver(existente)}
                  >
                    Manter arquivo
                  </Button>
                  <Button
                    color="red"
                    disabled={enviando}
                    onClick={() => void resolver(null)}
                  >
                    Apagar arquivo
                  </Button>
                </>
              )}
            </Group>
          </Stack>
        );
      }
      case TipoArquivo.OUTRO:
        return (
          <Alert color="yellow">
            Este arquivo não se resolve pela web (binário, rename, add/add sem
            texto ou submódulo). Resolva no editor local, na worktree{" "}
            <Code>{resultado.worktree}</Code>, e depois clique em Continuar.
          </Alert>
        );
      default:
        return assertNever(tipo);
    }
  };

  const culpados = resultado.culpados ?? [];
  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Text fw={700}>
            <Code>{conflito.data?.commit.slice(0, TAMANHO_HASH)}</Code>{" "}
            {conflito.data?.mensagem.split("\n")[0]}
          </Text>
          {conflito.data?.chamado && (
            <Text size="sm">Chamado: {conflito.data.chamado}</Text>
          )}
          {culpados.length > 0 && (
            <Text size="sm">
              Depende de: {culpados.map((c) => `#${c}`).join(", ")}
            </Text>
          )}
          <Group gap="xs">
            <Text size="sm">Worktree:</Text>
            <Code>{resultado.worktree}</Code>
            <CopyButton value={resultado.worktree}>
              {({ copied, copy }) => (
                <Button size="compact-xs" variant="default" onClick={copy}>
                  {copied ? "Copiado" : "Copiar"}
                </Button>
              )}
            </CopyButton>
          </Group>
        </Stack>
        <Button
          variant="default"
          disabled={enviando}
          onClick={() => guardar(aoSair)}
        >
          Voltar
        </Button>
      </Group>
      {desatualizado && (
        <Alert color="orange" title="O arquivo mudou no disco">
          <Stack align="flex-start">
            <Text size="sm">
              Alguém (o editor local ou outra aba) alterou o arquivo depois da
              leitura. Nada foi gravado.
            </Text>
            <Button
              size="xs"
              variant="light"
              onClick={() =>
                setConfirmar(() => descartando(() => void conteudo.refetch()))
              }
            >
              Recarregar do disco
            </Button>
          </Stack>
        </Alert>
      )}
      <Grid>
        <Grid.Col span={COLUNA_LISTA}>
          {arquivos.map((a) => (
            <NavLink
              key={a.caminho}
              active={a.caminho === atual?.caminho}
              // Resolução em voo limparia a edição de outro arquivo ao terminar.
              disabled={enviando}
              label={a.caminho}
              leftSection={a.resolvido ? "✓" : "●"}
              rightSection={
                <Badge variant="light">
                  {rotuloTipo(a.tipo as TipoArquivo)}
                </Badge>
              }
              onClick={() =>
                a.caminho !== atual?.caminho &&
                guardar(() => setEscolhido(a.caminho))
              }
            />
          ))}
        </Grid.Col>
        <Grid.Col span={COLUNA_CONTEUDO}>{corpo()}</Grid.Col>
      </Grid>
      <Modal
        opened={confirmar !== null}
        onClose={() => setConfirmar(null)}
        title="Descartar edição"
      >
        <Stack>
          <Text>{AVISO_DESCARTE}</Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              data-autofocus
              onClick={() => setConfirmar(null)}
            >
              Cancelar
            </Button>
            <Button
              color="red"
              onClick={() => {
                confirmar?.();
                setConfirmar(null);
              }}
            >
              Descartar
            </Button>
          </Group>
        </Stack>
      </Modal>
      <ModalReabrir
        caminho={reabrindo}
        aoConfirmar={() => void reabrir()}
        aoFechar={() => setReabrindo(null)}
      />
      <Modal
        opened={verBase}
        onClose={() => setVerBase(false)}
        title="Base"
        size="80%"
      >
        <Editor
          height={ALTURA}
          language={linguagem}
          path={`${Painel.VER_BASE}/${conflito.data?.commit ?? ""}/${atual?.caminho ?? ""}`}
          value={dados?.base ?? ""}
          theme={tema}
          options={SO_LEITURA}
        />
      </Modal>
    </Stack>
  );
}
