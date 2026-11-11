import {
  Alert,
  Button,
  Group,
  Modal,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Metodo, ErroApi, api } from "../api/cliente";
import { Escopo, TipoCampo, TipoErro } from "../api/enums";
import type { Campo, ConfigEditavel, ValorLido } from "../api/tipos";
import {
  ORIGEM_MOTOR,
  TABELA_AMBIENTE,
  achaCampo,
  alteracoesDe,
  chaveDe,
  type Escalar,
  type Formulario,
} from "../config";
import { notificarErro, notificarOk } from "./notificar";

const CHAVE = ["config"];

enum Aba {
  GERAL = "geral",
  REPOS = "repos",
  AMBIENTE = "ambiente",
  PLUGINS = "plugins",
}

type Valores = Formulario["valores"];

interface Linha {
  repo: string | null;
  tabela: string | null;
  chave: string;
  campo?: Campo;
  lido?: ValorLido;
}

const rotuloDe = (l: Linha): string =>
  l.campo?.rotulo ?? [l.tabela, l.chave].filter(Boolean).join(".");

function linhasDe(config: ConfigEditavel, repo: string | null): Linha[] {
  const declaradas = config.campos
    .filter((c) => (c.escopo === Escopo.REPO) === (repo !== null))
    .map((campo) => ({
      repo,
      tabela: campo.tabela,
      chave: campo.chave,
      campo,
      lido: config.valores.find(
        (v) => v.repo === repo && v.tabela === campo.tabela && v.chave === campo.chave,
      ),
    }));
  const livres = config.valores
    .filter(
      (v) => v.repo === repo && achaCampo(config.campos, v.repo, v.tabela, v.chave) === undefined,
    )
    .map((lido) => ({ repo, tabela: lido.tabela, chave: lido.chave, lido }));
  return [...declaradas, ...livres];
}

function Entrada({
  linha,
  valores,
  mudar,
  placeholder,
}: {
  linha: Linha;
  valores: Valores;
  mudar: (k: string, v: Escalar) => void;
  placeholder?: string;
}) {
  const k = chaveDe(linha.repo, linha.tabela, linha.chave);
  const { campo, lido } = linha;
  const label = rotuloDe(linha);
  const somenteLeitura = campo === undefined && lido?.editavel !== true;
  const atual = valores[k] ?? null;
  if (campo?.segredo) {
    return (
      <Group align="end">
        <PasswordInput
          label={label}
          style={{ flex: 1 }}
          autoComplete="new-password"
          placeholder={lido?.definido ? "definido" : "não definido"}
          value={typeof atual === "string" ? atual : ""}
          onChange={(e) => mudar(k, e.currentTarget.value)}
        />
        <Button
          variant="light"
          color="red"
          disabled={!lido?.definido || atual === null}
          onClick={() => mudar(k, null)}
        >
          Apagar
        </Button>
      </Group>
    );
  }
  if (campo?.tipo === TipoCampo.ESCOLHA) {
    return (
      <Select
        label={label}
        data={campo.opcoes}
        clearable
        placeholder={placeholder}
        value={typeof atual === "string" ? atual : null}
        onChange={(v) => mudar(k, v)}
      />
    );
  }
  if (campo?.tipo === TipoCampo.INTEIRO || typeof lido?.valor === "number") {
    return (
      <NumberInput
        label={label}
        readOnly={somenteLeitura}
        placeholder={placeholder}
        value={typeof atual === "number" ? atual : ""}
        onChange={(v) => mudar(k, typeof v === "number" ? v : null)}
      />
    );
  }
  if (typeof lido?.valor === "boolean") {
    return (
      <Switch
        label={label}
        disabled={somenteLeitura}
        checked={atual === true}
        onChange={(e) => mudar(k, e.currentTarget.checked)}
      />
    );
  }
  return (
    <TextInput
      label={label}
      readOnly={somenteLeitura}
      placeholder={placeholder}
      value={typeof atual === "string" ? atual : ""}
      onChange={(e) => mudar(k, e.currentTarget.value)}
    />
  );
}

function Lista({
  linhas,
  valores,
  mudar,
}: {
  linhas: Linha[];
  valores: Valores;
  mudar: (k: string, v: Escalar) => void;
}) {
  if (linhas.length === 0) return <Text c="dimmed">Nada a configurar.</Text>;
  return (
    <Stack>
      {linhas.map((l) => (
        <Entrada
          key={chaveDe(l.repo, l.tabela, l.chave)}
          linha={l}
          valores={valores}
          mudar={mudar}
        />
      ))}
    </Stack>
  );
}

function Editor({
  config,
  salvando,
  recusada,
  aoSalvar,
  aoRecarregar,
}: {
  config: ConfigEditavel;
  salvando: boolean;
  recusada: boolean;
  aoSalvar: (f: Formulario) => void;
  aoRecarregar: () => void;
}) {
  // Segredo fica fora do estado: ausente = não tocado.
  const [valores, setValores] = useState<Valores>(() =>
    Object.fromEntries(
      config.valores
        .filter(
          (v) => achaCampo(config.campos, v.repo, v.tabela, v.chave)?.segredo !== true,
        )
        .map((v) => [chaveDe(v.repo, v.tabela, v.chave), v.valor]),
    ),
  );
  const [reposCriados, setReposCriados] = useState<string[]>([]);
  const [reposRemovidos, setReposRemovidos] = useState<string[]>([]);
  const [novo, setNovo] = useState("");
  const formulario = { valores, reposCriados, reposRemovidos };
  const pendentes = alteracoesDe(config, formulario).length;
  const mudar = (k: string, v: Escalar) => setValores((a) => ({ ...a, [k]: v }));

  const nome = novo.trim();
  const repos = [...config.repos, ...reposCriados];
  const criar = () => {
    setReposCriados((r) => [...r, nome]);
    setReposRemovidos((r) => r.filter((x) => x !== nome));
    setNovo("");
  };
  const remover = (repo: string) => {
    if (reposCriados.includes(repo)) {
      setReposCriados((r) => r.filter((x) => x !== repo));
      setValores((a) =>
        Object.fromEntries(
          Object.entries(a).filter(([k]) => (JSON.parse(k) as [string])[0] !== repo),
        ),
      );
    } else setReposRemovidos((r) => [...r, repo]);
  };

  const topo = (l: Linha) => (l.tabela === null ? undefined : valores[chaveDe(null, l.tabela, l.chave)]);
  const geral = linhasDe(config, null);
  const doMotor = geral.filter((l) => (l.campo?.origem ?? ORIGEM_MOTOR) === ORIGEM_MOTOR);
  const plugins = geral.filter((l) => (l.campo?.origem ?? ORIGEM_MOTOR) !== ORIGEM_MOTOR);
  const origens = [...new Set(plugins.map((l) => l.campo?.origem ?? ""))];

  return (
    <Stack>
      {recusada && (
        <Alert color="orange" title="A config mudou">
          <Button size="xs" onClick={aoRecarregar}>
            Recarregar
          </Button>
        </Alert>
      )}
      <Tabs defaultValue={Aba.GERAL}>
        <Tabs.List>
          <Tabs.Tab value={Aba.GERAL}>Geral</Tabs.Tab>
          <Tabs.Tab value={Aba.REPOS}>Repos</Tabs.Tab>
          <Tabs.Tab value={Aba.AMBIENTE}>Ambiente</Tabs.Tab>
          <Tabs.Tab value={Aba.PLUGINS}>Plugins</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value={Aba.GERAL} pt="md">
          <Lista
            linhas={doMotor.filter((l) => l.tabela !== TABELA_AMBIENTE)}
            valores={valores}
            mudar={mudar}
          />
        </Tabs.Panel>
        <Tabs.Panel value={Aba.REPOS} pt="md">
          <Stack>
            {repos
              .filter((r) => !reposRemovidos.includes(r))
              .map((repo) => (
                <Stack key={repo} gap="xs">
                  <Group justify="space-between">
                    <Title order={5}>{repo}</Title>
                    <Button size="xs" color="red" variant="light" onClick={() => remover(repo)}>
                      Remover
                    </Button>
                  </Group>
                  <Stack>
                    {linhasDe(config, repo).map((l) => {
                      const herdado = topo(l);
                      return (
                        <Entrada
                          key={chaveDe(l.repo, l.tabela, l.chave)}
                          linha={l}
                          valores={valores}
                          mudar={mudar}
                          {...(herdado != null && { placeholder: String(herdado) })}
                        />
                      );
                    })}
                  </Stack>
                </Stack>
              ))}
            <Group align="end">
              <TextInput
                label="Novo repo"
                value={novo}
                onChange={(e) => setNovo(e.currentTarget.value)}
              />
              <Button
                disabled={nome === "" || repos.includes(nome)}
                onClick={criar}
              >
                Criar repo
              </Button>
            </Group>
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value={Aba.AMBIENTE} pt="md">
          <Lista
            linhas={doMotor.filter((l) => l.tabela === TABELA_AMBIENTE)}
            valores={valores}
            mudar={mudar}
          />
        </Tabs.Panel>
        <Tabs.Panel value={Aba.PLUGINS} pt="md">
          <Stack>
            {origens.length === 0 && <Text c="dimmed">Nenhum plugin declara chaves.</Text>}
            {origens.map((origem) => (
              <Stack key={origem} gap="xs">
                <Title order={5}>{origem}</Title>
                <Lista
                  linhas={plugins.filter((l) => (l.campo?.origem ?? "") === origem)}
                  valores={valores}
                  mudar={mudar}
                />
              </Stack>
            ))}
          </Stack>
        </Tabs.Panel>
      </Tabs>
      <Group justify="flex-end">
        <Button
          disabled={pendentes === 0}
          loading={salvando}
          onClick={() => aoSalvar(formulario)}
        >
          Salvar
        </Button>
      </Group>
    </Stack>
  );
}

export function ModalConfig({
  aberto,
  aoFechar,
}: {
  aberto: boolean;
  aoFechar: () => void;
}) {
  const cliente = useQueryClient();
  const [recusada, setRecusada] = useState(false);
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
      void cliente.invalidateQueries({ queryKey: ["repos"] });
      notificarOk("Configuração salva");
    },
    onError: (erro) => {
      setRecusada(erro instanceof ErroApi && erro.tipo === TipoErro.RECUSA);
      notificarErro(erro);
    },
  });
  const dados = config.data;

  return (
    <Modal opened={aberto} onClose={aoFechar} title="Configuração" size="xl">
      {config.error && <Alert color="red">{config.error.message}</Alert>}
      {dados && (
        <Editor
          key={`${dados.versao}:${config.dataUpdatedAt}`}
          config={dados}
          salvando={salvar.isPending}
          recusada={recusada}
          aoSalvar={(f) =>
            salvar.mutate({ alteracoes: alteracoesDe(dados, f), versao: dados.versao })
          }
          aoRecarregar={() => {
            setRecusada(false);
            void config.refetch();
          }}
        />
      )}
    </Modal>
  );
}
