import { Badge, Box, Group, Paper, Stack, Text } from "@mantine/core";
import type { JSX } from "react";
import type { VersaoListada } from "../api/tipos";
import { Link } from "../navegacao";
import { Pagina } from "../rotas";
import { plural } from "../plural";
import { FONTE_MONO } from "../tema";
import { INTERVALO_RELOGIO_MS, ha, useAgora } from "../tempo";
import { BarraSegmentada } from "./BarraSegmentada";

const TAMANHO_PONTO = 8;
const LARGURA_NUMERO = 90;
export const TEXTO_INDISPONIVEL = "indisponível — checkout local não encontrado";
const SEPARADOR = " · ";
export const TEXTO_NENHUMA_GRAVADA = "nenhuma versão gravada";

enum EstadoVersao {
  VERDE = "verde",
  PENDENCIAS = "pendências",
  CONFLITO = "conflito",
  NAO_VERIFICADA = "não verificada",
}

const COR: Record<EstadoVersao, string> = {
  [EstadoVersao.VERDE]: "green.6",
  [EstadoVersao.PENDENCIAS]: "yellow.6",
  [EstadoVersao.CONFLITO]: "red.6",
  [EstadoVersao.NAO_VERIFICADA]: "gray.6",
};

function estadoDa(v: VersaoListada): EstadoVersao {
  const r = v.verificacao;
  if (r === null) return EstadoVersao.NAO_VERIFICADA;
  if (r.verde) return EstadoVersao.VERDE;
  return r.conflitantes > 0 ? EstadoVersao.CONFLITO : EstadoVersao.PENDENCIAS;
}

export function LinhaVersao({
  repo,
  versao: v,
  bloqueada,
}: {
  repo: string;
  versao: VersaoListada;
  bloqueada: boolean;
}): JSX.Element {
  const estado = estadoDa(v);
  const r = v.verificacao;
  const agora = useAgora(INTERVALO_RELOGIO_MS);
  return (
    <Paper component="li" px="md" py="xs" radius={0}>
      <Group gap="sm" wrap="nowrap">
        <Box
          w={TAMANHO_PONTO}
          h={TAMANHO_PONTO}
          bg={COR[estado]}
          style={{ borderRadius: "50%", flexShrink: 0 }}
          title={estado}
        />
        <Link
          para={{ pagina: Pagina.VERSAO, repo, versao: v.numero }}
          ff={FONTE_MONO}
          fw={600}
          w={LARGURA_NUMERO}
        >
          {v.numero}
        </Link>
        <Text size="sm" c="dimmed" flex={1} truncate>
          {r === null
            ? estado
            : [
                estado,
                plural(r.presentes, "presente", "presentes"),
                plural(r.faltantes, "faltante", "faltantes"),
                plural(r.conflitantes, "conflitante", "conflitantes"),
              ].join(SEPARADOR)}
        </Text>
        {bloqueada && (
          <Badge variant="light" color="red">
            bloqueada
          </Badge>
        )}
        {r !== null && (
          <BarraSegmentada
            presentes={r.presentes}
            faltantes={r.faltantes}
            conflitantes={r.conflitantes}
          />
        )}
        <Stack gap={0} align="flex-end">
          <Text size="xs" c="dimmed" ff={FONTE_MONO}>
            {r === null ? "nunca verificada" : `verificada ${ha(r.verificado_em, agora)}`}
          </Text>
          <Text size="xs" c="dimmed" ff={FONTE_MONO}>
            {v.atualizada_em === null
              ? "nunca atualizada"
              : `atualizada ${ha(v.atualizada_em, agora)}`}
          </Text>
        </Stack>
      </Group>
    </Paper>
  );
}

export function ListaVersoes({
  repo,
  versoes,
  bloqueadas,
}: {
  repo: string;
  versoes: VersaoListada[];
  bloqueadas: string[];
}): JSX.Element {
  return (
    <Stack component="ul" gap={0} p={0} m={0} style={{ listStyle: "none" }}>
      {versoes.map((v) => (
        <LinhaVersao
          key={v.numero}
          repo={repo}
          versao={v}
          bloqueada={bloqueadas.includes(v.numero)}
        />
      ))}
    </Stack>
  );
}
