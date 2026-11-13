import { describe, expect, it } from "vitest";
import { TipoArquivo } from "./api/enums";
import type { PropostaDeBloco } from "./api/tipos";
import { EstadoBloco, Lado, aceitouLado, estadoDoBloco } from "./conflito";
import {
  SEM_PROPOSTAS,
  TituloLente,
  descartar,
  falhar,
  iniciar,
  invalidar,
  lenteSugerir,
  mostraGatilhos,
  podar,
  receber,
  trechoDaProposta,
  vigente,
} from "./proposta";

const { ABERTO, DECIDIDO, EDITADO } = EstadoBloco;
const ESTADOS = [ABERTO, DECIDIDO, EDITADO, ABERTO];
const proposta = (ordem: number, conteudo = "x\n"): PropostaDeBloco => ({
  ordem,
  conteudo,
  justificativa: "porque",
});

function pedido(estados = ESTADOS, alvo: number | null = null) {
  const r = iniciar(SEM_PROPOSTAS, estados, alvo);
  if (r === null) throw new Error("pedido esperado");
  return r;
}

describe("mostraGatilhos", () => {
  it.each([
    [false, TipoArquivo.CONTEUDO, false, false],
    [true, TipoArquivo.MODIFICADO_APAGADO, false, false],
    [true, TipoArquivo.OUTRO, false, false],
    [true, TipoArquivo.CONTEUDO, true, false],
    [true, TipoArquivo.CONTEUDO, false, true],
  ])(
    "gatilhos só em arquivo de conteúdo pendente com provedor disponível (%s %s %s)",
    (disponivel, tipo, resolvido, esperado) => {
      expect(mostraGatilhos(disponivel, tipo, resolvido)).toBe(esperado);
    },
  );
});

describe("lenteSugerir", () => {
  it("lente só em bloco aberto, sem ação durante um pedido", () => {
    expect(lenteSugerir(DECIDIDO, false)).toBeNull();
    expect(lenteSugerir(EDITADO, false)).toBeNull();
    expect(lenteSugerir(ABERTO, false)).toEqual({
      titulo: TituloLente.SUGERIR,
      acionavel: true,
    });
    expect(lenteSugerir(ABERTO, true)).toEqual({
      titulo: TituloLente.SUGERINDO,
      acionavel: false,
    });
  });
});

describe("iniciar", () => {
  it("o botão pede só os abertos e a lente só o próprio bloco", () => {
    expect(iniciar(SEM_PROPOSTAS, ESTADOS, null)?.ordens).toEqual([0, 3]);
    expect(iniciar(SEM_PROPOSTAS, ESTADOS, 3)?.ordens).toEqual([3]);
    expect(iniciar(SEM_PROPOSTAS, ESTADOS, 1)).toBeNull();
  });

  it("sem os estados do editor novo, o botão não pede nada", () => {
    expect(iniciar(invalidar(SEM_PROPOSTAS), [], null)).toBeNull();
  });

  it("com um pedido em andamento nenhum gatilho dispara outro", () => {
    const { estado } = pedido();
    expect(iniciar(estado, ESTADOS, null)).toBeNull();
    expect(iniciar(estado, ESTADOS, 0)).toBeNull();
  });
});

describe("receber", () => {
  it("a proposta fica pendente e uma nova substitui a anterior", () => {
    const a = pedido();
    const r1 = receber(a.estado, a.geracao, [proposta(0, "a\n")], ESTADOS);
    expect(r1.emAndamento).toBe(false);
    expect(r1.pendentes.get(0)?.conteudo).toBe("a\n");
    const b = iniciar(r1, ESTADOS, 0)!;
    const r2 = receber(b.estado, b.geracao, [proposta(0, "b\n")], ESTADOS);
    expect(r2.pendentes.get(0)?.conteudo).toBe("b\n");
  });

  it("resposta para bloco que deixou de estar aberto é descartada", () => {
    const a = pedido();
    const r = receber(
      a.estado,
      a.geracao,
      [proposta(0), proposta(3)],
      [ABERTO, DECIDIDO, EDITADO, EDITADO],
    );
    expect([...r.pendentes.keys()]).toEqual([0]);
  });
});

describe("podar e descartar", () => {
  const com = () => {
    const a = pedido();
    return receber(a.estado, a.geracao, [proposta(0), proposta(3)], ESTADOS);
  };

  it("decidir ou editar o bloco remove a proposta pendente", () => {
    const r = podar(com(), [DECIDIDO, DECIDIDO, EDITADO, ABERTO]);
    expect([...r.pendentes.keys()]).toEqual([3]);
  });

  it("descartar some só com a proposta daquele bloco", () => {
    expect([...descartar(com(), 0).pendentes.keys()]).toEqual([3]);
  });
});

describe("invalidar", () => {
  it("trocar de arquivo, recarregar, resolver ou reabrir descarta pendentes e respostas atrasadas", () => {
    const a = pedido();
    const novo = invalidar(a.estado);
    expect(receber(novo, a.geracao, [proposta(0)], ESTADOS)).toBe(novo);
    expect(vigente(novo, a.geracao)).toBe(false);
    expect(novo.pendentes.size).toBe(0);
    expect(iniciar(novo, ESTADOS, null)).not.toBeNull();
  });
});

describe("falhar", () => {
  it("falha encerra o pedido sem mexer nas pendentes", () => {
    const a = pedido();
    const r = receber(a.estado, a.geracao, [proposta(0)], ESTADOS);
    const b = iniciar(r, ESTADOS, 3)!;
    const f = falhar(b.estado, b.geracao);
    expect(f.emAndamento).toBe(false);
    expect(f.pendentes.size).toBe(1);
  });

  it("falha da geração velha não muda nada", () => {
    const a = pedido();
    const novo = invalidar(a.estado);
    expect(falhar(novo, a.geracao)).toBe(novo);
  });
});

describe("trechoDaProposta", () => {
  it("trecho da proposta termina em quebra de linha", () => {
    expect(trechoDaProposta("x")).toBe("x\n");
    expect(trechoDaProposta("x\n")).toBe("x\n");
    expect(trechoDaProposta("")).toBe("");
  });
});

describe("aplicar vale como decisão do bloco", () => {
  it("a proposta aplicada é DECIDIDO e não marca lado", () => {
    const original = "<<<<<<< a\nA\n=======\nB\n>>>>>>> b\n";
    const t = "resolvido\n";
    const d = { lado: Lado.PROPOSTA, texto: t };
    expect(estadoDoBloco(t, d)).toBe(DECIDIDO);
    expect(estadoDoBloco(original, d)).toBe(ABERTO);
    expect(aceitouLado(d, Lado.OURS)).toBe(false);
  });
});
