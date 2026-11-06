import { Modal } from "@mantine/core";
import type { VersionStatus } from "../api/tipos";
import { Status } from "./Status";

export interface Resultado {
  status: VersionStatus;
  auditado: boolean;
}

export function ModalResultado({
  resultado,
  aoFechar,
}: {
  resultado: Resultado | null;
  aoFechar: () => void;
}) {
  return (
    <Modal opened={resultado !== null} onClose={aoFechar} title="Resultado" size="xl">
      {resultado && <Status status={resultado.status} auditado={resultado.auditado} />}
    </Modal>
  );
}
