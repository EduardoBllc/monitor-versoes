import { notifications } from "@mantine/notifications";

export function notificarErro(erro: unknown): void {
  const mensagem = erro instanceof Error ? erro.message : String(erro);
  notifications.show({ color: "red", title: "Erro", message: mensagem });
}

export function notificarOk(mensagem: string): void {
  notifications.show({ color: "green", message: mensagem });
}
