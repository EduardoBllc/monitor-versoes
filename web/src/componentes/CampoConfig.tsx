import { Button, Group, NumberInput, PasswordInput, Select, Switch, Text, TextInput, Tooltip } from "@mantine/core";
import { TipoCampo } from "../api/enums";
import {
  EstadoSegredo,
  chaveDe,
  estadoSegredo,
  opcoesDe,
  textoDe,
  type Escalar,
  type Formulario,
  type Linha,
} from "../config";

export type Valores = Formulario["valores"];

export const rotuloDe = (l: Linha): string =>
  l.campo?.rotulo ?? [l.tabela, l.chave].filter(Boolean).join(".");

function Rotulo({ linha }: { linha: Linha }) {
  const texto = rotuloDe(linha);
  const descricao = linha.campo?.descricao;
  if (!descricao) return texto;
  return (
    <Group component="span" gap={4} display="inline-flex">
      {texto}
      <Tooltip label={descricao} multiline w={280} withArrow events={{ hover: true, focus: true, touch: true }}>
        <Text span c="dimmed" tabIndex={0} aria-label={descricao} style={{ cursor: "help" }}>
          ⓘ
        </Text>
      </Tooltip>
    </Group>
  );
}

export function Entrada({
  linha,
  valores,
  mudar,
  descricao,
}: {
  linha: Linha;
  valores: Valores;
  mudar: (k: string, v: Escalar) => void;
  descricao?: string;
}) {
  const k = chaveDe(linha.repo, linha.tabela, linha.chave);
  const { campo, lido } = linha;
  const label = <Rotulo linha={linha} />;
  const description = descricao ?? (campo?.padrao != null ? `Padrão: ${campo.padrao}` : undefined);
  const dica = campo?.exemplo || undefined;
  const somenteLeitura = lido?.editavel === false;
  const atual = valores[k] ?? null;
  if (campo?.segredo) {
    const estado = estadoSegredo(valores[k], lido?.definido === true);
    const apagar = estado === EstadoSegredo.APAGAR;
    const marcas = {
      [EstadoSegredo.APAGAR]: "será apagado",
      [EstadoSegredo.DEFINIDO]: "definido",
      [EstadoSegredo.NAO_DEFINIDO]: "não definido",
    };
    return (
      <Group align="end">
        <PasswordInput
          label={label}
          description={description}
          style={{ flex: 1 }}
          autoComplete="new-password"
          placeholder={marcas[estado]}
          disabled={somenteLeitura}
          value={typeof atual === "string" ? atual : ""}
          onChange={(e) => mudar(k, e.currentTarget.value)}
        />
        <Button
          variant="light"
          color="red"
          disabled={somenteLeitura || !lido?.definido}
          onClick={() => mudar(k, apagar ? "" : null)}
        >
          {apagar ? "Desfazer" : "Apagar"}
        </Button>
      </Group>
    );
  }
  if (campo?.tipo === TipoCampo.ESCOLHA) {
    return (
      <Select
        label={label}
        description={description}
        data={opcoesDe(campo, atual)}
        disabled={somenteLeitura}
        clearable
        placeholder={dica}
        value={typeof atual === "string" ? atual : null}
        onChange={(v) => mudar(k, v)}
      />
    );
  }
  if (campo?.tipo === TipoCampo.INTEIRO || typeof lido?.valor === "number") {
    return (
      <NumberInput
        label={label}
        description={description}
        readOnly={somenteLeitura}
        placeholder={dica}
        value={textoDe(atual)}
        onChange={(v) => mudar(k, typeof v === "number" ? v : "")}
      />
    );
  }
  if (typeof lido?.valor === "boolean") {
    return (
      <Switch
        label={label}
        disabled={somenteLeitura}
        checked={atual === true}
        onChange={(e) => mudar(k, e.currentTarget.checked)}
      />
    );
  }
  return (
    <TextInput
      label={label}
      description={description}
      readOnly={somenteLeitura}
      placeholder={dica}
      value={typeof atual === "string" ? atual : ""}
      onChange={(e) => mudar(k, e.currentTarget.value)}
    />
  );
}
