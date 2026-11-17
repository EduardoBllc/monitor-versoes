import { Button, Paper, Stack, Text } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JSX } from "react";
import { Metodo, api } from "../../api/cliente";
import { notificarErro } from "../../componentes/notificar";
import { consultaInscricoes, descreverRodada } from "../../inscricoes";

export function InscricaoDaVersao({
  repo,
  versao,
}: {
  repo: string;
  versao: string;
}): JSX.Element {
  const cliente = useQueryClient();
  const lista = useQuery(consultaInscricoes);
  const gravar = useMutation({
    mutationFn: (metodo: Metodo) =>
      api<void>(metodo, "/api/inscricoes", { repo, versao }),
    onError: notificarErro,
    onSettled: () =>
      cliente.invalidateQueries({ queryKey: consultaInscricoes.queryKey }),
  });
  const inscricao = lista.data?.find(
    (i) => i.repo === repo && i.versao === versao,
  );
  return (
    <Paper component="section" aria-label="Inscrição" p="sm">
      <Stack gap="xs">
        <Text fw={700}>Inscrição</Text>
        {lista.error && <Text c="red">{lista.error.message}</Text>}
        {inscricao ? (
          <>
            <Text size="sm">a cada {inscricao.intervalo}</Text>
            <Text size="sm" c="dimmed">
              última: {descreverRodada(inscricao.ultima)}
            </Text>
            <Button
              color="red"
              variant="light"
              disabled={gravar.isPending}
              onClick={() => gravar.mutate(Metodo.DELETE)}
            >
              Remover
            </Button>
          </>
        ) : (
          <Button
            disabled={lista.isLoading || gravar.isPending}
            onClick={() => gravar.mutate(Metodo.POST)}
          >
            Inscrever selecionada
          </Button>
        )}
      </Stack>
    </Paper>
  );
}
