import { Accordion, Text } from "@mantine/core";
import type { JSX } from "react";
import type { InscricaoVista, VerificacaoGravada } from "../../api/tipos";
import { descreverRodada } from "../../inscricoes";

const ITEM = "historico";

// Só a última de cada: a API não guarda histórico (Ruling 2 do plano da etapa 3).
export function Historico({
  gravada,
  inscricao,
}: {
  gravada: VerificacaoGravada | null | undefined;
  inscricao: InscricaoVista | undefined;
}): JSX.Element {
  return (
    <Accordion variant="contained">
      <Accordion.Item value={ITEM}>
        <Accordion.Control>Histórico</Accordion.Control>
        <Accordion.Panel>
          <Text size="sm">
            Última verificação:{" "}
            {gravada
              ? `${new Date(gravada.verificado_em).toLocaleString()} · ${gravada.status.verde ? "verde" : "com pendências"}`
              : "nenhuma"}
          </Text>
          <Text size="sm">
            Última rodada da inscrição:{" "}
            {inscricao?.ultima ? descreverRodada(inscricao.ultima) : "nenhuma"}
          </Text>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}
