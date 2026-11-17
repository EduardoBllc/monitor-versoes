import { Breadcrumbs, Text } from "@mantine/core";
import type { JSX } from "react";
import { Link, useRota } from "../navegacao";
import { Pagina, caminhoDa, type Rota } from "../rotas";
import { FONTE_MONO } from "../tema";

const NOME_DA_TRILHA = "Trilha";

interface Passo {
  rotulo: string;
  rota: Rota;
  mono?: boolean;
}

function passos(rota: Rota): Passo[] {
  const inicio: Passo = { rotulo: "Início", rota: { pagina: Pagina.INICIO } };
  switch (rota.pagina) {
    case Pagina.INICIO:
      return [inicio];
    case Pagina.CONFIG:
      return [inicio, { rotulo: "Configuração", rota }];
    case Pagina.REPO:
      return [inicio, { rotulo: rota.repo, rota }];
    case Pagina.VERSAO:
      return [
        inicio,
        { rotulo: rota.repo, rota: { pagina: Pagina.REPO, repo: rota.repo } },
        { rotulo: rota.versao, rota, mono: true },
      ];
  }
}

/** Início › repo › versão; o último passo é a página aberta, sem link. */
export function Trilha(): JSX.Element {
  const lista = passos(useRota());
  return (
    <nav aria-label={NOME_DA_TRILHA}>
      <Breadcrumbs separatorMargin="xs">
        {lista.map((p, i) => {
          const ff = p.mono ? FONTE_MONO : undefined;
          return i === lista.length - 1 ? (
            <Text key={caminhoDa(p.rota)} size="sm" fw={600} ff={ff}>
              {p.rotulo}
            </Text>
          ) : (
            <Link key={caminhoDa(p.rota)} para={p.rota} size="sm" c="dimmed" ff={ff}>
              {p.rotulo}
            </Link>
          );
        })}
      </Breadcrumbs>
    </nav>
  );
}
