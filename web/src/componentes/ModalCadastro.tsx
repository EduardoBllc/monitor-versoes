import { Button, Group, Modal, Stack, TextInput } from "@mantine/core";
import { useState, type SyntheticEvent } from "react";
import { Metodo, api } from "../api/cliente";

export function ModalCadastro({
  aberto,
  aoFechar,
  aoCadastrar,
}: {
  aberto: boolean;
  aoFechar: () => void;
  aoCadastrar: (nome: string) => void;
}) {
  const [nome, setNome] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  const salvar = async (e: SyntheticEvent) => {
    e.preventDefault();
    setEnviando(true);
    try {
      await api<void>(Metodo.POST, "/api/repos", { nome });
      aoCadastrar(nome.trim());
      setNome("");
      setErro("");
      aoFechar();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : String(falha));
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Modal opened={aberto} onClose={aoFechar} title="Cadastrar repositório">
      <form onSubmit={(e) => void salvar(e)}>
        <Stack>
          <TextInput
            label="nome"
            placeholder="nome canônico, sem caminho"
            data-autofocus
            value={nome}
            onChange={(e) => setNome(e.currentTarget.value)}
            error={erro || undefined}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={aoFechar}>
              Cancelar
            </Button>
            <Button
              type="submit"
              loading={enviando}
              disabled={nome.trim() === ""}
            >
              Salvar
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
