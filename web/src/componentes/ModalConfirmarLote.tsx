import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import type { VersionStatus } from "../api/tipos";
import { Status } from "./Status";

export function ModalConfirmarLote({
  status,
  versao,
  aoConfirmar,
  aoCancelar,
}: {
  status: VersionStatus | null;
  versao: string;
  aoConfirmar: () => void;
  aoCancelar: () => void;
}) {
  return (
    <Modal
      opened={status !== null}
      onClose={aoCancelar}
      title={`Atualizar ${versao}`}
      size="xl"
    >
      {status && (
        <Stack>
          <Status status={status} auditado={false} />
          <Text size="sm" c="dimmed">
            {status.faltantes?.length} commits entram na branch {versao} e são
            publicados na origin.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={aoCancelar}>
              Cancelar
            </Button>
            <Button color="orange" data-autofocus onClick={aoConfirmar}>
              Aplicar e publicar
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
