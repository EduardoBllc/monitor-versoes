import { Button, Group, Tooltip } from "@mantine/core";
import type { JSX } from "react";
import { FaseAtualizacao } from "../atualizacao";

const SEM_CHECKOUT = "checkout local não encontrado";

export interface PropsAcoesVersao {
  fase: FaseAtualizacao;
  liberada: boolean;
  disponivel: boolean;
  ocupado: boolean;
  // Só experiência de uso: quem decide o continuar é o motor.
  continuarBarrado: boolean;
  aoVerificar: (auditar: boolean) => void;
  aoAtualizar: () => void;
  aoContinuar: () => void;
  aoAbortar: () => void;
  aoOrfaos: () => void;
  aoInscricoes: () => void;
}

export function AcoesVersao(p: PropsAcoesVersao): JSX.Element {
  const semAcao = p.ocupado || !p.disponivel;
  const vazia = p.fase === FaseAtualizacao.VAZIA;
  const pendente = vazia || p.fase === FaseAtualizacao.BLOQUEADA;
  const aplicando =
    p.fase === FaseAtualizacao.PREVIA || p.fase === FaseAtualizacao.APLICANDO;
  return (
    <Group gap="xs">
      <Tooltip label={SEM_CHECKOUT} disabled={p.disponivel}>
        <Group gap="xs">
          <Button disabled={semAcao} onClick={() => p.aoVerificar(false)}>
            Verificar
          </Button>
          {p.liberada && (
            <Button
              variant="light"
              disabled={semAcao}
              onClick={() => p.aoVerificar(true)}
            >
              Auditar tag agora
            </Button>
          )}
          {pendente ? (
            <>
              <Button
                color={vazia ? "yellow" : "red"}
                disabled={p.ocupado || p.continuarBarrado}
                onClick={p.aoContinuar}
              >
                {vazia ? "Registrar vazio" : "Continuar"}
              </Button>
              <Button
                variant="light"
                color="red"
                disabled={p.ocupado}
                onClick={p.aoAbortar}
              >
                Abortar
              </Button>
            </>
          ) : (
            <Button
              color="orange"
              disabled={semAcao || aplicando}
              onClick={p.aoAtualizar}
            >
              Atualizar
            </Button>
          )}
          <Button variant="light" disabled={semAcao} onClick={p.aoOrfaos}>
            Órfãos
          </Button>
        </Group>
      </Tooltip>
      <Button variant="default" onClick={p.aoInscricoes}>
        Inscrições
      </Button>
    </Group>
  );
}
