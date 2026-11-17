import { Button } from "@mantine/core";
import { Spotlight, spotlight } from "@mantine/spotlight";
import { useQueries, useQuery } from "@tanstack/react-query";
import type { JSX } from "react";
import { Metodo, api, consultaRepos } from "../api/cliente";
import type { ChamadoIndexado, VersaoListada } from "../api/tipos";
import { ir } from "../navegacao";
import { OrigemVersoes, chaveVersoes } from "../versoes";
import { acoesDaPaleta } from "./paleta";

const ATALHO = "mod+K";

export function Paleta(): JSX.Element {
  const repos = useQuery(consultaRepos).data ?? [];
  const chamados = useQuery({
    queryKey: ["chamados"],
    queryFn: () => api<ChamadoIndexado[]>(Metodo.GET, "/api/chamados"),
  }).data;
  // Só a lista gravada: a paleta não pode disparar git fetch.
  const listas = useQueries({
    queries: repos.map((r) => ({
      queryKey: chaveVersoes(r.nome, OrigemVersoes.GRAVADAS),
      queryFn: () =>
        api<VersaoListada[]>(
          Metodo.GET,
          `/api/repos/${encodeURIComponent(r.nome)}/versoes?gravadas=true`,
        ),
    })),
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
  return (
    <Button variant="default" onClick={spotlight.open}>
      Buscar ⌘K
    </Button>
  );
}
