import { describe, expect, it } from "vitest";
import {
  Lado,
  aceitar,
  blocoEm,
  blocos,
  localizar,
  recolher,
  temMarcadores,
} from "./conflito";

const BLOCO_2_VIAS = "antes\n<<<<<<< ours\nA\n=======\nB\n>>>>>>> theirs\n";
const BLOCO_3_VIAS =
  "<<<<<<< ours\nA\n||||||| base\nB\n=======\nC\n>>>>>>> theirs\n";
const DOIS_BLOCOS =
  "x\r\n<<<<<<< ours\r\nA1\r\n=======\r\nB1\r\n>>>>>>> theirs\r\nmeio\r\n" +
  "<<<<<<< ours\r\nA2\r\n||||||| base\r\nO2\r\n=======\r\nB2\r\n>>>>>>> theirs\r\nfim";

describe("blocos", () => {
  it("de 2 vias não tem base", () => {
    expect(blocos(BLOCO_2_VIAS)).toEqual([
      { inicio: 2, fim: 6, ours: "A\n", base: null, theirs: "B\n" },
    ]);
  });

  it("de 3 vias traz a base", () => {
    expect(blocos(BLOCO_3_VIAS)).toEqual([
      { inicio: 1, fim: 7, ours: "A\n", base: "B\n", theirs: "C\n" },
    ]);
  });

  it("acha cada bloco com as próprias linhas", () => {
    expect(blocos(DOIS_BLOCOS)).toEqual([
      { inicio: 2, fim: 6, ours: "A1\r\n", base: null, theirs: "B1\r\n" },
      { inicio: 8, fim: 14, ours: "A2\r\n", base: "O2\r\n", theirs: "B2\r\n" },
    ]);
  });
});

describe("blocoEm", () => {
  it("acha o bloco pela linha do <<<<<<< e nada se ela não abre bloco", () => {
    expect(blocoEm(DOIS_BLOCOS, 8)).toEqual(blocos(DOIS_BLOCOS)[1]);
    expect(blocoEm(DOIS_BLOCOS, 7)).toBeUndefined();
  });
});

describe("aceitar", () => {
  const primeiro = "<<<<<<< ours\r\nA1\r\n=======\r\nB1\r\n>>>>>>> theirs\r\n";

  it.each([
    [Lado.OURS, "A2\r\n"],
    [Lado.THEIRS, "B2\r\n"],
    [Lado.AMBOS, "A2\r\nB2\r\n"],
    [Lado.BASE, "O2\r\n"],
  ])("%s reescreve só o bloco escolhido", (lado, trecho) => {
    const [, bloco] = blocos(DOIS_BLOCOS);
    expect(aceitar(DOIS_BLOCOS, bloco!, lado)).toBe(
      `x\r\n${primeiro}meio\r\n${trecho}fim`,
    );
  });

  it("bloco no fim sem quebra de linha não ganha quebra", () => {
    const texto = "<<<<<<< ours\nA\n=======\nB\n>>>>>>> theirs";
    const [bloco] = blocos(texto);
    expect(aceitar(texto, bloco!, Lado.THEIRS)).toBe("B");
  });
});

it.each([
  ["a\nb\n", false],
  [BLOCO_2_VIAS, true],
  [BLOCO_3_VIAS, true],
  ["========\n", false],
  ["a <<<<<<< b\n", false],
  ["a\r\n=======\r\nb\r\n", true],
  ["a\u2028=======\n", false],
])("temMarcadores(%j) = %s", (texto, esperado) => {
  expect(temMarcadores(texto)).toBe(esperado);
});

describe("localizar", () => {
  it("acha cada trecho em ordem, sem voltar", () => {
    expect(localizar("X\nm\nX\n", ["X\n", "X\n"])).toEqual([
      { inicio: 1, fim: 1 },
      { inicio: 3, fim: 3 },
    ]);
  });

  it("trecho vazio fica ancorado logo depois do anterior", () => {
    expect(localizar("a\nX\nb\n", ["X\n", ""])).toEqual([
      { inicio: 2, fim: 2 },
      { inicio: 3, fim: 2 },
    ]);
  });

  it("trecho não achado vira faixa vazia no cursor", () => {
    expect(localizar("a\nb\n", ["Z\n"])).toEqual([{ inicio: 1, fim: 0 }]);
  });

  it("aceita CRLF", () => {
    expect(localizar("a\r\nX\r\nY\r\nb\r\n", ["X\r\nY\r\n"])).toEqual([
      { inicio: 2, fim: 3 },
    ]);
  });
});

describe("recolher", () => {
  it("esconde o que fica fora do contexto das faixas visíveis", () => {
    expect(recolher(20, [{ inicio: 10, fim: 11 }], 3)).toEqual([
      { inicio: 1, fim: 6 },
      { inicio: 15, fim: 20 },
    ]);
  });

  it("junta contextos que se encostam e não esconde uma linha só", () => {
    expect(
      recolher(
        20,
        [
          { inicio: 5, fim: 5 },
          { inicio: 9, fim: 9 },
        ],
        3,
      ),
    ).toEqual([{ inicio: 13, fim: 20 }]);
  });

  it("faixa vazia também ganha contexto", () => {
    expect(recolher(20, [{ inicio: 5, fim: 4 }], 3)).toEqual([
      { inicio: 8, fim: 20 },
    ]);
  });

  it("sem faixa visível não esconde nada", () => {
    expect(recolher(20, [], 3)).toEqual([]);
  });
});
