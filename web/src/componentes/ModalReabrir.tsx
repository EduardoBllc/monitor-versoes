import { Button, Code, Group, Modal, Stack, Text } from "@mantine/core";

export function ModalReabrir({
  caminho,
  aoConfirmar,
  aoFechar,
}: {
  caminho: string | null;
  aoConfirmar: () => void;
  aoFechar: () => void;
}) {
  return (
    <Modal opened={caminho !== null} onClose={aoFechar} title="Reabrir arquivo">
      <Stack>
        <Text>
          Isto descarta a resolução de <Code>{caminho}</Code> e volta os
          marcadores.
        </Text>
        <Group justify="flex-end">
          <Button variant="default" data-autofocus onClick={aoFechar}>
            Cancelar
          </Button>
          <Button color="red" onClick={aoConfirmar}>
            Reabrir
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
