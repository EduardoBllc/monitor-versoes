import { Alert, Button, Group, Stack, Text } from "@mantine/core";
import { useMutation } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ErroApi, Metodo, api } from "../api/cliente";
import { EstadoTeste, TipoErro, type PecaTestavel } from "../api/enums";
import type { ConfigEditavel, ResultadoTeste } from "../api/tipos";
import { alteracoesDe, type Formulario } from "../config";
import { assinatura, type Destino } from "../configSecoes";
import { notificarErro } from "./notificar";

const COR: Partial<Record<string, string>> = {
  [EstadoTeste.OK]: "green",
  [EstadoTeste.FALHA]: "red",
};

export function TestarSecao({
  config,
  formulario,
  destino,
  peca,
  resultado,
  aoResultado,
  aoRecusa,
  children,
}: {
  config: ConfigEditavel;
  formulario: Formulario;
  destino: Destino;
  peca: PecaTestavel;
  resultado: ResultadoTeste | undefined;
  aoResultado: (assinatura: string, r: ResultadoTeste) => void;
  aoRecusa: () => void;
  children?: ReactNode;
}) {
  const testar = useMutation({
    // A assinatura é a do formulário enviado: editar durante o teste não herda o resultado.
    mutationFn: ({ formulario: f }: { formulario: Formulario; assinatura: string }) =>
      api<ResultadoTeste>(Metodo.POST, "/api/config/testar", {
        alteracoes: alteracoesDe(config, f),
        versao: config.versao,
        peca,
        repo: typeof destino === "string" ? null : destino.repo,
      }),
    onSuccess: (r, { assinatura: a }) => aoResultado(a, r),
    onError: (erro, { assinatura: a }) => {
      // O que o salvar recusaria (ex.: caminho inexistente) é falha da seção, não da página.
      if (erro instanceof ErroApi && erro.tipo === TipoErro.ENTRADA) {
        aoResultado(a, { estado: EstadoTeste.FALHA, detalhe: erro.message, correcao: "" });
        return;
      }
      if (erro instanceof ErroApi && erro.tipo === TipoErro.RECUSA) aoRecusa();
      notificarErro(erro);
    },
  });
  return (
    <Stack gap="sm">
      <Group>
        <Button
          variant="default"
          loading={testar.isPending}
          onClick={() => testar.mutate({ formulario, assinatura: assinatura(destino, config, formulario) })}
        >
          Testar
        </Button>
        {children}
      </Group>
      {resultado && (
        <Alert color={COR[resultado.estado] ?? "gray"} title={resultado.estado}>
          <Text size="sm">{resultado.detalhe}</Text>
          {resultado.correcao && (
            <Text size="sm" c="dimmed">
              Correção: {resultado.correcao}
            </Text>
          )}
        </Alert>
      )}
    </Stack>
  );
}
