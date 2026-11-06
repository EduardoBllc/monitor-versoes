import { Button, Group, Modal, Stack, Text } from "@mantine/core";

export function ModalAbortar({
  aberto,
  aoConfirmar,
  aoFechar,
}: {
  aberto: boolean;
  aoConfirmar: () => void;
  aoFechar: () => void;
}) {
  return (
    <Modal opened={aberto} onClose={aoFechar} title="Abortar cherry-pick">
      <Stack>
        <Text>A resolução de conflito que está na worktree será descartada.</Text>
        <Group justify="flex-end">
          <Button variant="default" data-autofocus onClick={aoFechar}>
            Cancelar
          </Button>
          <Button color="red" onClick={aoConfirmar}>
            Abortar
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
