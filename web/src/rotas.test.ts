import { expect, it } from "vitest";
import { caminhoDe, lerCaminho } from "./rotas";

it("ida e volta com repo e versão", () => {
  expect(caminhoDe("meu-repo", "14.0.0")).toBe("/r/meu-repo/v/14.0.0");
  expect(lerCaminho("/r/meu-repo/v/14.0.0")).toEqual({
    repo: "meu-repo",
    versao: "14.0.0",
  });
});

it("só repo, e raiz", () => {
  expect(lerCaminho(caminhoDe("meu-repo"))).toEqual({ repo: "meu-repo" });
  expect(caminhoDe()).toBe("/");
  expect(lerCaminho("/")).toEqual({});
});

it("codifica caracteres especiais", () => {
  expect(lerCaminho(caminhoDe("a b", "1/2"))).toEqual({
    repo: "a b",
    versao: "1/2",
  });
});
