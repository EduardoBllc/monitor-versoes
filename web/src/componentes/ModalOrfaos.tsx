import {
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Metodo, api } from "../api/cliente";
import type { JulgamentoOrfao, OrfaoDaVersao } from "../api/tipos";
import { caminhoJulgamento, caminhoOrfaos, rotuloJulgamento } from "../orfaos";
import { notificarErro } from "./notificar";

interface Pedido {
  hash: string;
  chamado: string | null;
  motivo: string;
}

export function ModalOrfaos({
  aberto,
  aoFechar,
  repo,
  versao,
}: {
  aberto: boolean;
  aoFechar: () => void;
  repo: string;
  versao: string;
}) {
  const cliente = useQueryClient();
  const chave = ["orfaos", repo, versao];
  const [escolhido, setEscolhido] = useState<string | null>(null);
  const [chamado, setChamado] = useState("");
  const [nenhum, setNenhum] = useState(false);
  const [motivo, setMotivo] = useState("");
  // Cada leitura faz git fetch: só carrega com o modal aberto.
  const lista = useQuery({
    queryKey: chave,
    queryFn: () =>
      api<OrfaoDaVersao[]>(Metodo.GET, caminhoOrfaos(repo, versao)),
    enabled: aberto,
  });
  const julgar = useMutation({
    mutationFn: (p: Pedido) =>
      api<JulgamentoOrfao>(
        Metodo.POST,
        caminhoJulgamento(repo, versao, p.hash),
        { chamado: p.chamado, motivo: p.motivo },
      ),
    onSuccess: () => {
      setEscolhido(null);
      setChamado("");
      setNenhum(false);
      setMotivo("");
    },
    onError: notificarErro,
    onSettled: () => cliente.invalidateQueries({ queryKey: chave }),
  });

  return (
    <Modal
      opened={aberto}
      onClose={aoFechar}
      title={`Órfãos de ${repo} ${versao}`}
      size="xl"
    >
      {lista.isLoading && <Loader mx="auto" display="block" />}
      {lista.error && <Text c="red">{lista.error.message}</Text>}
      {lista.data?.length === 0 && (
        <Text c="dimmed">Nenhum commit órfão nesta versão.</Text>
      )}
      <Table highlightOnHover>
        <Table.Tbody>
          {lista.data?.map((o) => (
            <Table.Tr
              key={o.hash_origem}
              onClick={() => setEscolhido(o.hash_origem)}
              bg={
                o.hash_origem === escolhido
                  ? "var(--mantine-primary-color-light)"
                  : undefined
              }
              style={{ cursor: "pointer" }}
            >
              <Table.Td ff="monospace">{o.hash_origem.slice(0, 8)}</Table.Td>
              <Table.Td>{new Date(o.data).toLocaleDateString()}</Table.Td>
              <Table.Td>{o.assunto}</Table.Td>
              <Table.Td>{rotuloJulgamento(o)}</Table.Td>
              <Table.Td c="dimmed">{o.julgamento?.motivo ?? ""}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {escolhido !== null && (
        <Stack mt="md" gap="xs">
          <Text size="sm">Julgar {escolhido.slice(0, 8)}</Text>
          <Group align="end">
            <TextInput
              label="Chamado"
              value={chamado}
              disabled={nenhum}
              onChange={(e) => setChamado(e.currentTarget.value)}
            />
            <Checkbox
              label="não pertence a chamado nenhum"
              checked={nenhum}
              onChange={(e) => setNenhum(e.currentTarget.checked)}
            />
          </Group>
          <TextInput
            label="Motivo"
            value={motivo}
            onChange={(e) => setMotivo(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button
              loading={julgar.isPending}
              disabled={!nenhum && chamado.trim() === ""}
              onClick={() =>
                julgar.mutate({
                  hash: escolhido,
                  chamado: nenhum ? null : chamado.trim(),
                  motivo,
                })
              }
            >
              Gravar
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
