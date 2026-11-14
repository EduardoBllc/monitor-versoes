import { Button, Code, Group, Loader, Select, Text, Tooltip } from "@mantine/core";
import type { ReactNode } from "react";
import type { NovidadeVista, RepoOption, VersionOption } from "../api/tipos";

const SEM_CHECKOUT = "checkout local não encontrado";
const CARREGANDO = "carregando…";
const girando = (sim?: boolean) => (sim ? <Loader size="xs" /> : undefined);

export interface PropsBarra {
  repos: RepoOption[];
  carregandoRepos?: boolean;
  repo?: string;
  versoes: VersionOption[];
  carregandoVersoes?: boolean;
  versao?: string;
  ocupado: boolean;
  bloqueadas?: string[];
  novidades: NovidadeVista[];
  aoEscolherRepo: (nome: string) => void;
  aoEscolherVersao: (numero: string) => void;
  aoVerificar: (auditar: boolean) => void;
  aoCriar: () => void;
  aoInscricoes: () => void;
  aoOrfaos: () => void;
  aoConfigurar: () => void;
  // Espaço dos botões Atualizar/Abortar, preenchido pela tarefa do fluxo de atualização.
  slotAtualizar?: ReactNode;
}

// Uma linha só: a barra tem altura fixa; o resto fica no title do "+N".
function AvisoVersao({ novidades }: { novidades: NovidadeVista[] }) {
  const [primeira, ...resto] = novidades;
  if (primeira === undefined) return null;
  return (
    <Text size="xs" c="orange">
      {primeira.texto} <Code>{primeira.comando}</Code>
      {resto.length > 0 && (
        <Text span inherit title={resto.map((n) => `${n.texto} ${n.comando}`).join("\n")}>
          {` +${resto.length}`}
        </Text>
      )}
    </Text>
  );
}

export function Barra(p: PropsBarra) {
  const liberada =
    p.versoes.find((v) => v.numero === p.versao)?.liberada === true;
  const disponivel = p.repos.find((r) => r.nome === p.repo)?.caminho != null;
  const semAcao = p.ocupado || !disponivel || p.versao === undefined;
  return (
    <Group h="100%" px="md" gap="sm" wrap="wrap">
      <Select
        aria-label="Repositório"
        placeholder={p.carregandoRepos ? CARREGANDO : "repositório"}
        searchable
        w={220}
        disabled={p.carregandoRepos}
        rightSection={girando(p.carregandoRepos)}
        value={p.repo ?? null}
        data={p.repos.map((r) => ({
          value: r.nome,
          label: r.nome,
          disabled: r.caminho === null,
        }))}
        renderOption={({ option }) => (
          <Tooltip label={SEM_CHECKOUT} disabled={option.disabled !== true}>
            <span>{option.label}</span>
          </Tooltip>
        )}
        onChange={(v) => v && p.aoEscolherRepo(v)}
        allowDeselect={false}
      />
      <Select
        aria-label="Versão"
        placeholder={p.carregandoVersoes ? CARREGANDO : "versão"}
        w={200}
        disabled={!disponivel || p.carregandoVersoes}
        rightSection={girando(p.carregandoVersoes)}
        value={p.versao ?? null}
        data={p.versoes.map((v) => ({
          value: v.numero,
          label: [
            v.numero,
            v.liberada && "liberada",
            p.bloqueadas?.includes(v.numero) && "bloqueada",
          ]
            .filter(Boolean)
            .join("  ·  "),
        }))}
        onChange={(v) => v && p.aoEscolherVersao(v)}
        allowDeselect={false}
      />
      <Tooltip
        label={SEM_CHECKOUT}
        disabled={disponivel || p.repo === undefined}
      >
        <Group gap="xs">
          <Button disabled={semAcao} onClick={() => p.aoVerificar(false)}>
            Verificar
          </Button>
          {liberada && (
            <Button
              variant="light"
              disabled={semAcao}
              onClick={() => p.aoVerificar(true)}
            >
              Auditar tag agora
            </Button>
          )}
          {p.slotAtualizar}
          <Button variant="light" disabled={semAcao} onClick={p.aoOrfaos}>
            Órfãos
          </Button>
          <Button
            variant="light"
            color="orange"
            disabled={p.ocupado || !disponivel}
            onClick={p.aoCriar}
          >
            Nova versão
          </Button>
        </Group>
      </Tooltip>
      <Group gap="xs" ml="auto">
        <AvisoVersao novidades={p.novidades} />
        <Button variant="default" onClick={p.aoInscricoes}>
          Inscrições
        </Button>
        <Button variant="default" disabled={p.ocupado} onClick={p.aoConfigurar}>
          Configuração
        </Button>
      </Group>
    </Group>
  );
}
