import { Button } from "@mantine/core";
import { notifications } from "@mantine/notifications";

// Fica até o operador fechar: um pick aberto não pode passar despercebido.
export function notificarPendencia(
  id: string,
  mensagem: string,
  aoIr: () => void,
): void {
  const fechar = () => notifications.hide(id);
  notifications.show({
    id,
    color: "yellow",
    autoClose: false,
    message: (
      <>
        {mensagem}{" "}
        <Button
          size="compact-xs"
          variant="light"
          onClick={() => {
            aoIr();
            fechar();
          }}
        >
          Abrir
        </Button>
      </>
    ),
  });
}
