import {
  Alert,
  Box,
  Button,
  Divider,
  Group,
  Loader,
  Modal,
  NavLink,
  Paper,
  Progress,
  Stack,
  Text,
  TextInput,
  Title,
  UnstyledButton,
  VisuallyHidden,
  getDefaultZIndex,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { CHAVE_REPOS, Metodo, ErroApi, api } from "../api/cliente";
import { PecaTestavel, TipoErro } from "../api/enums";
import type { ConfigEditavel, ResultadoTeste } from "../api/tipos";
import {
  ORIGEM_MOTOR,
  achaCampo,
  alteracoesDe,
  chaveDe,
  type Escalar,
  type Formulario,
  type Linha,
} from "../config";
import {
  GrupoLateral,
  LATERAL,
  Marca,
  NOME_SECAO,
  Secao,
  comTeste,
  gravarPulados,
  lerPulados,
  linhasDaSecao,
  marcaDe,
  pendencias,
  testeVigente,
  type Destino,
  type Segmento,
} from "../configSecoes";
import { Entrada, type Valores } from "./CampoConfig";
import { notificarErro, notificarOk } from "./notificar";
import { SecaoRepo } from "./SecaoRepo";
import { TestarSecao } from "./TestarSecao";

const CHAVE = ["config"];

const TITULO: Record<Secao, string> = { ...NOME_SECAO, [Secao.NOVO_REPO]: "Adicionar repo" };

const ABERTURA: Record<Secao, string> = {
  [Secao.PRS]:
    "É por ela que o monitor descobre a qual PR cada commit pertence. Sem ela, os commits saem só do grep na principal.",
  [Secao.TAREFAS]: "De onde vêm os chamados que o monitor acompanha.",
  [Secao.VERSOES]: "Como as versões são nomeadas, liberadas e em que branches vivem.",
  [Secao.NOVO_REPO]: "O nome pelo qual o monitor chama o repo.",
  [Secao.AVANCADO]: "Ajustes com padrão razoável; raramente precisam mudar.",
};

// Só as conexões têm teste e só elas podem ser puladas.
const PECA: Partial<Record<Secao, PecaTestavel>> = {
  [Secao.PRS]: PecaTestavel.PRS,
  [Secao.TAREFAS]: PecaTestavel.TAREFAS,
};

const SINAL: Partial<Record<Marca, { texto: string; cor: string; nome: string }>> = {
  [Marca.PRONTA]: { texto: "✓", cor: "green", nome: "pronta" },
  [Marca.PENDENTE]: { texto: "●", cor: "orange", nome: "pendente" },
  [Marca.FALHOU]: { texto: "✕", cor: "red", nome: "teste falhou" },
};

const COR_BARRA: Partial<Record<Marca, string>> = { [Marca.PRONTA]: "green", [Marca.FALHOU]: "red" };

const mesmo = (a: Destino, b: Destino) => JSON.stringify(a) === JSON.stringify(b);
const nomeDe = (d: Destino) => (typeof d === "string" ? NOME_SECAO[d] : d.repo);
const origemDe = (l: Linha) => l.campo?.origem ?? ORIGEM_MOTOR;

function Sinal({ marca }: { marca: Marca }) {
  const s = SINAL[marca];
  if (!s) return null;
  return (
    <>
      <Text span c={s.cor} aria-hidden>
        {s.texto}
      </Text>
      <VisuallyHidden>{s.nome}</VisuallyHidden>
    </>
  );
}

function Campos({
  linhas,
  valores,
  mudar,
}: {
  linhas: Linha[];
  valores: Valores;
  mudar: (k: string, v: Escalar) => void;
}) {
  if (linhas.length === 0) return <Text c="dimmed">Nada a configurar.</Text>;
  const origens = [...new Set(linhas.map(origemDe))];
  return (
    <Stack>
      {origens.map((origem) => (
        <Fragment key={origem}>
          {origem !== ORIGEM_MOTOR && <Divider label={`Campos do plugin ${origem}`} labelPosition="left" />}
          {linhas
            .filter((l) => origemDe(l) === origem)
            .map((l) => (
              <Entrada key={chaveDe(l.repo, l.tabela, l.chave)} linha={l} valores={valores} mudar={mudar} />
            ))}
        </Fragment>
      ))}
    </Stack>
  );
}

function Barra({ segmentos, abrir, continuar }: { segmentos: Segmento[]; abrir: (d: Destino) => void; continuar: () => void }) {
  return (
    <Paper withBorder p="sm">
      <Group wrap="nowrap">
        <Group grow gap="xs" align="flex-start" style={{ flex: 1 }}>
          {segmentos.map((s) => (
            <UnstyledButton key={s.nome} onClick={() => abrir(s.destino)}>
              <Progress
                aria-hidden
                size="sm"
                value={s.marca === Marca.PENDENTE ? 0 : 100}
                color={COR_BARRA[s.marca] ?? "gray"}
              />
              <Text size="xs" c="dimmed" mt={4}>
                {s.nome}
                {s.marca !== Marca.PENDENTE && <> <Sinal marca={s.marca} /></>}
              </Text>
            </UnstyledButton>
          ))}
        </Group>
        <Button onClick={continuar}>Continuar</Button>
      </Group>
    </Paper>
  );
}

function Editor({
  config,
  salvando,
  recusada,
  retomar,
  sujo,
  aoSalvar,
  aoRecusa,
  aoRecarregar,
}: {
  config: ConfigEditavel;
  salvando: boolean;
  recusada: boolean;
  retomar: Destino | null;
  sujo: RefObject<boolean>;
  aoSalvar: (f: Formulario, destino: Destino) => void;
  aoRecusa: () => void;
  aoRecarregar: () => void;
}) {
  // Segredo fica fora do estado: ausente = não tocado.
  const [formulario, setFormulario] = useState<Formulario>(() => ({
    valores: Object.fromEntries(
      config.valores
        .filter((v) => v.editavel && achaCampo(config.campos, v.repo, v.tabela, v.chave)?.segredo !== true)
        .map((v) => [chaveDe(v.repo, v.tabela, v.chave), v.valor]),
    ),
    reposCriados: [],
    reposRemovidos: [],
  }));
  const [testes, setTestes] = useState<Record<string, ResultadoTeste>>({});
  const [pulados, setPulados] = useState(lerPulados);
  const proximaDe = (f: Formulario) => pendencias(config, f, testes, pulados).proxima ?? Secao.PRS;
  const [destino, setDestino] = useState<Destino>(() => retomar ?? proximaDe(formulario));
  const [novo, setNovo] = useState("");

  const pendentes = alteracoesDe(config, formulario).length;
  useEffect(() => {
    sujo.current = pendentes > 0;
    return () => {
      sujo.current = false;
    };
  }, [pendentes, sujo]);

  const { segmentos, proxima } = pendencias(config, formulario, testes, pulados);
  const marca = (d: Destino) => marcaDe(d, config, formulario, testes, pulados);
  const mudar = (k: string, v: Escalar) => setFormulario((f) => ({ ...f, valores: { ...f.valores, [k]: v } }));

  const repos = [...config.repos, ...formulario.reposCriados].filter((r) => !formulario.reposRemovidos.includes(r));
  const nome = novo.trim();
  const criar = () => {
    setFormulario((f) => ({ ...f, reposCriados: [...f.reposCriados, nome] }));
    setNovo("");
    setDestino({ repo: nome });
  };
  const remover = (repo: string) => {
    const f = formulario.reposCriados.includes(repo)
      ? {
          ...formulario,
          reposCriados: formulario.reposCriados.filter((x) => x !== repo),
          valores: Object.fromEntries(
            Object.entries(formulario.valores).filter(([k]) => (JSON.parse(k) as [string])[0] !== repo),
          ),
        }
      : { ...formulario, reposRemovidos: [...formulario.reposRemovidos, repo] };
    setFormulario(f);
    setDestino(proximaDe(f));
  };
  const alternarPulo = (s: Secao) => {
    const p = new Set(pulados);
    if (!p.delete(s)) p.add(s);
    gravarPulados(p);
    setPulados(p);
  };

  const testar = (d: Destino, peca: PecaTestavel, extra?: ReactNode) => (
    <TestarSecao
      config={config}
      formulario={formulario}
      destino={d}
      peca={peca}
      resultado={testeVigente(d, config, formulario, testes)}
      aoResultado={(f, r, recusa) => setTestes((t) => comTeste(t, d, config, f, r, recusa))}
      aoRecusa={aoRecusa}
    >
      {extra}
    </TestarSecao>
  );

  let conteudo: ReactNode;
  if (typeof destino !== "string") {
    conteudo = (
      <SecaoRepo
        config={config}
        formulario={formulario}
        repo={destino.repo}
        mudar={mudar}
        aoRemover={() => remover(destino.repo)}
      >
        {testar(destino, PecaTestavel.REPO)}
      </SecaoRepo>
    );
  } else if (destino === Secao.NOVO_REPO) {
    conteudo = (
      <Group align="end">
        <TextInput label="Nome" style={{ flex: 1 }} value={novo} onChange={(e) => setNovo(e.currentTarget.value)} />
        <Button disabled={nome === "" || [...config.repos, ...formulario.reposCriados].includes(nome)} onClick={criar}>
          Criar
        </Button>
      </Group>
    );
  } else {
    const peca = PECA[destino];
    conteudo = (
      <>
        <Campos linhas={linhasDaSecao(config, formulario, destino)} valores={formulario.valores} mudar={mudar} />
        {peca &&
          testar(
            destino,
            peca,
            pulados.has(destino) ? (
              <Button variant="subtle" onClick={() => alternarPulo(destino)}>
                Desfazer
              </Button>
            ) : (
              marca(destino) !== Marca.PRONTA && (
                <Button variant="subtle" onClick={() => alternarPulo(destino)}>
                  Não uso isso
                </Button>
              )
            ),
          )}
      </>
    );
  }

  return (
    <Stack gap={0} style={{ flex: 1, minHeight: 0 }}>
      <Group align="flex-start" wrap="nowrap" gap="xl" style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <Box component="nav" aria-label="Seções da configuração" w={240} style={{ flexShrink: 0 }}>
          {LATERAL.map(({ grupo, secoes }) => (
            <Fragment key={grupo}>
              <Text size="xs" tt="uppercase" c="dimmed" fw={700} mt="md" mb={4} px="sm">
                {grupo}
              </Text>
              {[...(grupo === GrupoLateral.REPOSITORIOS ? repos.map((repo) => ({ repo })) : []), ...secoes].map(
                (d) => (
                  <NavLink
                    key={JSON.stringify(d)}
                    component="button"
                    label={nomeDe(d)}
                    active={mesmo(d, destino)}
                    aria-current={mesmo(d, destino) ? "page" : undefined}
                    rightSection={<Sinal marca={marca(d)} />}
                    onClick={() => setDestino(d)}
                  />
                ),
              )}
            </Fragment>
          ))}
        </Box>
        <Stack style={{ flex: 1, minWidth: 0 }} maw={760} pt="md">
          {recusada && (
            <Alert color="orange" title="A config mudou">
              <Button size="xs" onClick={aoRecarregar}>
                Recarregar
              </Button>
            </Alert>
          )}
          {proxima !== null && (
            <Barra segmentos={segmentos} abrir={setDestino} continuar={() => setDestino(proxima)} />
          )}
          {typeof destino === "string" && (
            <div>
              <Title order={3}>{TITULO[destino]}</Title>
              <Text c="dimmed">{ABERTURA[destino]}</Text>
            </div>
          )}
          <Fragment key={JSON.stringify(destino)}>{conteudo}</Fragment>
        </Stack>
      </Group>
      <Group justify="flex-end" pt="sm" style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}>
        {pendentes > 0 && (
          <Text c="dimmed" size="sm">
            {pendentes === 1 ? "1 alteração não salva" : `${pendentes} alterações não salvas`}
          </Text>
        )}
        <Button disabled={pendentes === 0} loading={salvando} onClick={() => aoSalvar(formulario, destino)}>
          Salvar
        </Button>
      </Group>
    </Stack>
  );
}

export function ModalConfig({ aberto, aoFechar }: { aberto: boolean; aoFechar: () => void }) {
  const cliente = useQueryClient();
  const [recusada, setRecusada] = useState(false);
  // Salvar recarrega o editor na seção aberta; recarregar e fechar voltam à próxima pendência.
  const [retomar, setRetomar] = useState<Destino | null>(null);
  const [confirmar, setConfirmar] = useState(false);
  const sujo = useRef(false);
  const config = useQuery({
    queryKey: CHAVE,
    queryFn: () => api<ConfigEditavel>(Metodo.GET, "/api/config"),
    enabled: aberto,
    gcTime: 0,
  });
  const salvar = useMutation({
    mutationFn: (corpo: { alteracoes: ReturnType<typeof alteracoesDe>; versao: string }) =>
      api<ConfigEditavel>(Metodo.PUT, "/api/config", corpo),
    onSuccess: (nova) => {
      setRecusada(false);
      cliente.setQueryData(CHAVE, nova);
      void cliente.invalidateQueries({ queryKey: CHAVE_REPOS });
      notificarOk("Configuração salva");
    },
    onError: (erro) => {
      setRecusada(erro instanceof ErroApi && erro.tipo === TipoErro.RECUSA);
      notificarErro(erro);
    },
  });
  const dados = config.data;
  const fechar = () => {
    setConfirmar(false);
    setRetomar(null);
    aoFechar();
  };

  return (
    <Modal
      opened={aberto}
      onClose={() => {
        // O Escape chega às duas modais; a confirmação não o escuta, e quem a fecha é este handler.
        if (confirmar) setConfirmar(false);
        else if (sujo.current) setConfirmar(true);
        else fechar();
      }}
      title="Configuração"
      fullScreen
      // Rodapé fixo: o corpo ocupa a altura e só o meio rola.
      styles={{
        content: { display: "flex", flexDirection: "column" },
        body: { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" },
      }}
    >
      {config.isLoading && <Loader mx="auto" display="block" />}
      {config.error && <Alert color="red">{config.error.message}</Alert>}
      {dados && (
        <Editor
          key={`${dados.versao}:${config.dataUpdatedAt}`}
          config={dados}
          salvando={salvar.isPending}
          recusada={recusada}
          retomar={retomar}
          sujo={sujo}
          aoSalvar={(f, destino) => {
            setRetomar(destino);
            salvar.mutate({ alteracoes: alteracoesDe(dados, f), versao: dados.versao });
          }}
          aoRecusa={() => setRecusada(true)}
          aoRecarregar={() => {
            setRecusada(false);
            setRetomar(null);
            void config.refetch();
          }}
        />
      )}
      <Modal
        opened={confirmar}
        onClose={() => setConfirmar(false)}
        title="Descartar as alterações não salvas?"
        centered
        closeOnEscape={false}
        zIndex={getDefaultZIndex("modal") + 1}
      >
        <Group justify="flex-end">
          <Button variant="default" data-autofocus onClick={() => setConfirmar(false)}>
            Continuar editando
          </Button>
          <Button color="red" onClick={fechar}>
            Descartar
          </Button>
        </Group>
      </Modal>
    </Modal>
  );
}
