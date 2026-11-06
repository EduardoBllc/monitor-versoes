import { Button, Group, Modal, Table, Text } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Metodo, api } from "../api/cliente";
import type { InscricaoVista } from "../api/tipos";
import { notificarErro } from "./notificar";

const CHAVE = ["inscricoes"];

function ultima(i: InscricaoVista): string {
  if (i.ultima === null) return "nunca executou";
  const quando = new Date(i.ultima.hora).toLocaleString();
  return `${quando} ${i.ultima.desfecho}${i.ultima.mensagem ? `: ${i.ultima.mensagem}` : ""}`;
}

export function ModalInscricoes({
  aberto,
  aoFechar,
  repo,
  versao,
}: {
  aberto: boolean;
  aoFechar: () => void;
  repo?: string;
  versao?: string;
}) {
  const cliente = useQueryClient();
  const lista = useQuery({
    queryKey: CHAVE,
    queryFn: () => api<InscricaoVista[]>(Metodo.GET, "/api/inscricoes"),
    enabled: aberto,
  });
  const gravar = useMutation({
    mutationFn: (escrita: () => Promise<void>) => escrita(),
    onError: notificarErro,
    onSettled: () => cliente.invalidateQueries({ queryKey: CHAVE }),
  });

  return (
    <Modal opened={aberto} onClose={aoFechar} title="Inscrições" size="xl">
      <Group mb="md">
        <Button
          disabled={repo === undefined || versao === undefined}
          onClick={() =>
            gravar.mutate(() =>
              api<void>(Metodo.POST, "/api/inscricoes", { repo, versao }),
            )
          }
        >
          Inscrever selecionada
        </Button>
      </Group>
      {lista.error && <Text c="red">{lista.error.message}</Text>}
      {lista.data?.length === 0 && (
        <Text c="dimmed">
          Nenhuma inscrição. Selecione repo e versão e inscreva.
        </Text>
      )}
      <Table>
        <Table.Tbody>
          {lista.data?.map((i) => (
            <Table.Tr key={`${i.repo}@${i.versao}`}>
              <Table.Td>{i.versao}</Table.Td>
              <Table.Td>{i.repo}</Table.Td>
              <Table.Td>a cada {i.intervalo}</Table.Td>
              <Table.Td c="dimmed">{ultima(i)}</Table.Td>
              <Table.Td>
                <Button
                  size="xs"
                  color="red"
                  variant="light"
                  onClick={() =>
                    gravar.mutate(() =>
                      api<void>(Metodo.DELETE, "/api/inscricoes", {
                        repo: i.repo,
                        versao: i.versao,
                      }),
                    )
                  }
                >
                  Remover
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Modal>
  );
}
