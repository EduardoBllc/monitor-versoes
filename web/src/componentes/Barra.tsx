import { Button, Group, Select, Tooltip } from "@mantine/core";
import type { ReactNode } from "react";
import type { RepoOption, VersionOption } from "../api/tipos";

const SEM_CHECKOUT = "checkout local não encontrado";

export interface PropsBarra {
  repos: RepoOption[];
  repo?: string;
  versoes: VersionOption[];
  versao?: string;
  ocupado: boolean;
  bloqueadas?: string[];
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

export function Barra(p: PropsBarra) {
  const liberada =
    p.versoes.find((v) => v.numero === p.versao)?.liberada === true;
  const disponivel = p.repos.find((r) => r.nome === p.repo)?.caminho != null;
  const semAcao = p.ocupado || !disponivel || p.versao === undefined;
  return (
    <Group h="100%" px="md" gap="sm" wrap="wrap">
      <Select
        aria-label="Repositório"
        placeholder="repositório"
        searchable
        w={220}
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
        placeholder="versão"
        w={200}
        disabled={!disponivel}
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
