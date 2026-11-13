import { Box, Button, CloseButton, Group, Paper, Select, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";
import type { ConfigEditavel } from "../api/tipos";
import { chaveDe, vazio, type Escalar, type Formulario, type Linha } from "../config";
import { escolhido, grupoEscolhidoPor, linhasDoRepo } from "../configSecoes";
import { Entrada, rotuloDe } from "./CampoConfig";

const chave = (l: Linha) => chaveDe(l.repo, l.tabela, l.chave);

export function SecaoRepo({
  config,
  formulario,
  repo,
  mudar,
  aoRemover,
  children,
}: {
  config: ConfigEditavel;
  formulario: Formulario;
  repo: string;
  mudar: (k: string, v: Escalar) => void;
  aoRemover: () => void;
  children: ReactNode;
}) {
  const { valores } = formulario;
  const { proprias, sobrescritas, sobrescreviveis } = linhasDoRepo(config, formulario, repo);
  const escritas = new Set(sobrescritas.map(chave));
  // Campos do plugin que o repo escolhe por conta própria: moram sob a sobrescrita que o escolheu.
  const doPlugin = (escolha: Linha): Linha[] => {
    const grupo = grupoEscolhidoPor(escolha);
    if (grupo === undefined) return [];
    const origem = escolhido(config, formulario, grupo, repo);
    return [...sobrescritas, ...sobrescreviveis].filter(
      (l) => l.campo?.grupo === (grupo as string) && l.campo.origem === origem,
    );
  };
  const aninhadas = new Set(sobrescritas.flatMap(doPlugin).map(chave));
  const geral = (l: Linha): string => {
    const v = valores[chaveDe(null, l.tabela, l.chave)];
    return `Geral: ${(vazio(v) ? l.campo?.padrao : String(v)) || "não definido"}`;
  };
  const campo = (l: Linha) => (
    <Group key={chave(l)} align="end" wrap="nowrap">
      <Box flex={1}>
        <Entrada linha={l} valores={valores} mudar={mudar} descricao={geral(l)} />
      </Box>
      {escritas.has(chave(l)) && (
        <CloseButton aria-label={`Voltar ${rotuloDe(l)} ao geral`} onClick={() => mudar(chave(l), null)} />
      )}
    </Group>
  );
  const opcoes = sobrescreviveis
    .filter((l) => !aninhadas.has(chave(l)))
    .map((l) => ({ value: chave(l), label: rotuloDe(l) }));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{repo}</Title>
        <Button color="red" variant="light" onClick={aoRemover}>
          Remover
        </Button>
      </Group>
      <Text c="dimmed">O clone local deste repositório e o que nele difere do geral.</Text>
      {proprias.map((l) => (
        <Entrada key={chave(l)} linha={l} valores={valores} mudar={mudar} />
      ))}
      {children}
      <Paper withBorder p="md">
        <Stack>
          <Text fw={600}>Diferente do geral</Text>
          {sobrescritas
            .filter((l) => !aninhadas.has(chave(l)))
            .map((l) => (
              <Stack key={chave(l)} gap="xs">
                {campo(l)}
                {doPlugin(l).length > 0 && (
                  <Stack ml="md" pl="md" style={{ borderLeft: "2px solid var(--mantine-color-default-border)" }}>
                    {doPlugin(l).map(campo)}
                  </Stack>
                )}
              </Stack>
            ))}
          {opcoes.length > 0 && (
            <Select
              aria-label="Sobrescrever campo"
              placeholder="+ sobrescrever campo"
              data={opcoes}
              value={null}
              onChange={(k) => k !== null && mudar(k, "")}
              w={280}
            />
          )}
        </Stack>
      </Paper>
    </Stack>
  );
}
