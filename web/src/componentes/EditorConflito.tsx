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
  SimpleGrid,
  Stack,
  Text,
  useComputedColorScheme,
} from "@mantine/core";
import { DiffEditor, Editor, loader, type OnMount } from "@monaco-editor/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as monaco from "monaco-editor";
import TrabalhadorEditor from "monaco-editor/editor/editor.worker?worker";
import { useEffect, useRef, useState } from "react";
import { ErroApi, Metodo, api } from "../api/cliente";
import { TipoArquivo, TipoErro, assertNever } from "../api/enums";
import type {
  ArquivoDoConflito,
  AtualizarResult,
  ConflitoAberto,
  ConteudoDoConflito,
  Resolucao,
} from "../api/tipos";
import {
  AVISO_DESCARTE,
  Lado,
  aceitar,
  blocoEm,
  blocos,
  temMarcadores,
} from "../conflito";
import { ModalReabrir } from "./ModalReabrir";
import { notificarErro, notificarOk } from "./notificar";
import { TAMANHO_HASH } from "./PainelBloqueio";

// Monaco do bundle e worker local, sem CDN: o daemon só serve 127.0.0.1.
self.MonacoEnvironment = { getWorker: () => new TrabalhadorEditor() };
loader.config({ monaco });

const LINGUAGEM = "plaintext";
const ALTURA = "60vh";
const COMANDO_ACEITAR = "monitor-versoes.aceitar";
const COLUNA_LISTA = 3;
const COLUNA_CONTEUDO = 9;

enum Tema {
  CLARO = "light",
  ESCURO = "vs-dark",
}

enum RotaConflito {
  RESOLUCAO = "resolucao",
  REABERTURA = "reabertura",
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

const ACOES: readonly (readonly [Lado, string])[] = [
  [Lado.THEIRS, "Aceitar theirs"],
  [Lado.OURS, "Aceitar ours"],
  [Lado.AMBOS, "Ambos"],
  [Lado.BASE, "Base"],
];

const SO_LEITURA = { readOnly: true, minimap: { enabled: false } };

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

function Resultado({
  modelo,
  texto,
  somenteLeitura,
  tema,
  aoMudar,
}: {
  modelo: string;
  texto: string;
  somenteLeitura: boolean;
  tema: Tema;
  aoMudar: (texto: string) => void;
}) {
  const registros = useRef<monaco.IDisposable[]>([]);
  useEffect(() => () => registros.current.forEach((r) => r.dispose()), []);

  // A ação de bloco edita o modelo (undo funciona) e o onChange leva ao estado.
  const montar: OnMount = (editor, m) => {
    registros.current.push(
      m.editor.addCommand({
        id: COMANDO_ACEITAR,
        run: (_acesso: unknown, inicio: number, lado: Lado) => {
          const modelo = editor.getModel();
          // Pela linha, não pelo índice: lente atrasada não reescreve outro bloco.
          const bloco = modelo && blocoEm(modelo.getValue(), inicio);
          if (!modelo || !bloco) return;
          editor.pushUndoStop();
          editor.executeEdits(COMANDO_ACEITAR, [
            {
              range: modelo.getFullModelRange(),
              text: aceitar(modelo.getValue(), bloco, lado),
            },
          ]);
          editor.pushUndoStop();
        },
      }),
      m.languages.registerCodeLensProvider(LINGUAGEM, {
        provideCodeLenses: (modelo: monaco.editor.ITextModel) => ({
          lenses:
            modelo !== editor.getModel()
              ? []
              : blocos(modelo.getValue()).flatMap((b) =>
                  ACOES.filter(
                    ([lado]) => lado !== Lado.BASE || b.base !== null,
                  ).map(([lado, titulo]) => ({
                    range: new m.Range(b.inicio, 1, b.inicio, 1),
                    command: {
                      id: COMANDO_ACEITAR,
                      title: titulo,
                      arguments: [b.inicio, lado],
                    },
                  })),
                ),
        }),
      }),
    );
  };

  return (
    <Editor
      height={ALTURA}
      language={LINGUAGEM}
      path={modelo}
      value={texto}
      theme={tema}
      options={{ readOnly: somenteLeitura, minimap: { enabled: false } }}
      onMount={montar}
      onChange={(v) => aoMudar(v ?? "")}
    />
  );
}

export default function EditorConflito({
  repo,
  versao,
  resultado,
  aoSair,
  aoMudar,
}: {
  repo: string;
  versao: string;
  resultado: AtualizarResult;
  aoSair: () => void;
  aoMudar: (estado: EstadoConflitoWeb) => void;
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

  const texto = edicao?.texto ?? dados?.disco ?? "";
  const sujo = edicao !== null && edicao.texto !== dados?.disco;
  // OUTRO só se resolve fora da web; quem barra o Continuar nesse caso é o motor.
  const pendente = arquivos.some(
    (a) => !a.resolvido && a.tipo !== TipoArquivo.OUTRO,
  );

  useEffect(() => aoMudar({ pendente, sujo }), [pendente, sujo, aoMudar]);

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
    }
  };

  const reabrir = async () => {
    const caminho = reabrindo;
    setReabrindo(null);
    if (caminho !== null) await enviar(RotaConflito.REABERTURA, { caminho });
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
    const id = `${conflito.data?.commit ?? ""}/${atual.caminho}`;
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
            <SimpleGrid cols={3}>
              <Text fw={700}>theirs — commit aplicado</Text>
              <Text fw={700}>resultado</Text>
              <Text fw={700}>ours — alvo</Text>
              <Editor
                key={id}
                height={ALTURA}
                language={LINGUAGEM}
                path={modelo(Painel.THEIRS)}
                value={dados.theirs ?? ""}
                theme={tema}
                options={SO_LEITURA}
              />
              <Resultado
                key={id}
                modelo={modelo(Painel.RESULTADO)}
                texto={texto}
                somenteLeitura={atual.resolvido}
                tema={tema}
                aoMudar={editar}
              />
              <Editor
                key={id}
                height={ALTURA}
                language={LINGUAGEM}
                path={modelo(Painel.OURS)}
                value={dados.ours ?? ""}
                theme={tema}
                options={SO_LEITURA}
              />
            </SimpleGrid>
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
              language={LINGUAGEM}
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
            Este arquivo não se resolve pela web (binário, renomeado ou
            adicionado nos dois lados). Resolva no editor local, na worktree{" "}
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
          language={LINGUAGEM}
          path={`${Painel.VER_BASE}/${conflito.data?.commit ?? ""}/${atual?.caminho ?? ""}`}
          value={dados?.base ?? ""}
          theme={tema}
          options={SO_LEITURA}
        />
      </Modal>
    </Stack>
  );
}
