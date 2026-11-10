import { Button, Group, Modal, Stack, Text, TextInput } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type SyntheticEvent } from "react";
import { Metodo, api } from "../api/cliente";
import { notificarErro } from "./notificar";
import type { Avaliacao, Sugestao } from "../api/tipos";

const DEBOUNCE_MS = 200;

export function ModalCriar({
  repo,
  existentes,
  aberto,
  aoFechar,
  aoCriar,
}: {
  repo: string;
  existentes: readonly string[];
  aberto: boolean;
  aoFechar: () => void;
  aoCriar: (numero: string) => void;
}) {
  const [numero, setNumero] = useState("");
  const [atrasado] = useDebouncedValue(numero.trim(), DEBOUNCE_MS);
  const base = `/api/repos/${encodeURIComponent(repo)}/versoes`;
  const sugestoes = useQuery({
    queryKey: ["sugestoes", repo, existentes],
    queryFn: () =>
      api<Sugestao[]>(Metodo.POST, `${base}/sugestoes`, { existentes }),
    enabled: aberto,
  });
  useEffect(() => {
    if (sugestoes.error) notificarErro(sugestoes.error);
  }, [sugestoes.error]);
  const fechar = () => {
    setNumero("");
    aoFechar();
  };
  const avaliacao = useQuery({
    queryKey: ["avaliacao", repo, existentes, atrasado],
    queryFn: () =>
      api<Avaliacao>(Metodo.POST, `${base}/avaliacao`, {
        numero: atrasado,
        existentes,
      }),
    enabled: aberto && atrasado !== "",
  });

  const pronto =
    numero.trim() === atrasado &&
    atrasado !== "" &&
    avaliacao.data !== undefined &&
    avaliacao.data.erro === "" &&
    avaliacao.data.previa !== "";
  const erro =
    atrasado === ""
      ? undefined
      : avaliacao.data?.erro || avaliacao.error?.message;

  const confirmar = (e: SyntheticEvent) => {
    e.preventDefault();
    if (!pronto) return;
    aoCriar(atrasado);
    setNumero("");
    aoFechar();
  };

  return (
    <Modal opened={aberto} onClose={fechar} title="Nova versão">
      <form onSubmit={confirmar}>
        <Stack>
          <TextInput
            label="número"
            placeholder="X.Y.Z"
            data-autofocus
            value={numero}
            onChange={(e) => setNumero(e.currentTarget.value)}
            error={erro}
          />
          <Group gap="xs">
            {sugestoes.data?.map((s) => (
              <Button
                key={s.numero}
                variant="light"
                size="xs"
                onClick={() => setNumero(s.numero)}
              >
                {s.tipo === null ? s.numero : `${s.numero} · ${s.tipo}`}
              </Button>
            ))}
          </Group>
          {pronto && <Text size="sm">{avaliacao.data?.previa}</Text>}
          <Text size="sm" c="dimmed">
            A branch sai da base, o VERSAO é commitado e o lote vai para a
            origin.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={fechar}>
              Cancelar
            </Button>
            <Button type="submit" color="orange" disabled={!pronto}>
              Criar e publicar
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
