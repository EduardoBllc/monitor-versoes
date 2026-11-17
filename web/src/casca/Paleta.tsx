import { Button } from "@mantine/core";
import { useOs, type UseOSReturnValue } from "@mantine/hooks";
import { Spotlight, spotlight } from "@mantine/spotlight";
import { useQueries, useQuery } from "@tanstack/react-query";
import type { JSX } from "react";
import { consultaIndiceChamados, consultaRepos } from "../api/cliente";
import { ir } from "../navegacao";
import { OrigemVersoes, consultaVersoes } from "../versoes";
import { acoesDaPaleta } from "./paleta";

// "mod" é ⌘ no macOS e Ctrl nos outros, como o rótulo.
const ATALHO = "mod+K";
const MACOS: UseOSReturnValue = "macos";

enum RotuloAtalho {
  MAC = "⌘K",
  OUTROS = "Ctrl+K",
}

export function Paleta(): JSX.Element {
  const repos = useQuery(consultaRepos).data ?? [];
  const chamados = useQuery(consultaIndiceChamados).data;
  // Só a lista gravada: a paleta não pode disparar git fetch.
  const listas = useQueries({
    queries: repos.map((r) => consultaVersoes(r.nome, OrigemVersoes.GRAVADAS)),
  });
  const versoes = Object.fromEntries(
    repos.map((r, i) => [r.nome, listas[i]?.data ?? []]),
  );
  const acoes = acoesDaPaleta(repos, versoes, chamados ?? []).map((a) => ({
    id: a.id,
    label: a.rotulo,
    description: a.descricao,
    onClick: () => ir(a.rota),
  }));
  return (
    <Spotlight
      actions={acoes}
      shortcut={ATALHO}
      nothingFound="Nada encontrado"
      searchProps={{ placeholder: "Buscar repo, versão ou chamado" }}
    />
  );
}

export function BotaoPaleta(): JSX.Element {
  const atalho = useOs() === MACOS ? RotuloAtalho.MAC : RotuloAtalho.OUTROS;
  return (
    <Button variant="default" onClick={spotlight.open}>
      Buscar {atalho}
    </Button>
  );
}
