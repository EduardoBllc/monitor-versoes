import { Modal } from "@mantine/core";
import type { Resultado } from "../execucoes";
import { Status } from "./Status";

export function ModalResultado({
  resultado,
  aoFechar,
}: {
  resultado: Resultado | null;
  aoFechar: () => void;
}) {
  return (
    <Modal
      opened={resultado !== null}
      onClose={aoFechar}
      title="Resultado"
      size="xl"
    >
      {resultado && (
        <Status status={resultado.status} auditado={resultado.auditado} />
      )}
    </Modal>
  );
}
