import { describe, expect, it } from "vitest";
import { linguagemDe } from "./linguagem";

const LINGUAGENS = [
  { id: "python", extensions: [".py"] },
  { id: "json", extensions: [".json"] },
  { id: "dockerfile", filenames: ["Dockerfile"] },
];

describe("linguagemDe", () => {
  it.each([
    ["scripts/a.py", "python"],
    ["x/INDICES.JSON", "json"],
    ["infra/Dockerfile", "dockerfile"],
    ["a.xyz", "plaintext"],
  ])("%s é %s", (caminho, esperado) => {
    expect(linguagemDe(caminho, LINGUAGENS)).toBe(esperado);
  });
});
