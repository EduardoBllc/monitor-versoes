import { describe, expect, it } from "vitest";
import { Lado, aceitar, blocos, temMarcadores } from "./conflito";

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
