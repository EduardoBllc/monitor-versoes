import { afterEach, expect, it, vi } from "vitest";
import { ErroApi, Metodo, api } from "./cliente";
import { TipoErro } from "./enums";

const CONFLITO = 409;

afterEach(() => vi.unstubAllGlobals());

it("lança ErroApi com o tipo do corpo em status de erro", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ tipo: TipoErro.OCUPADO, mensagem: "ocupado" }), {
        status: CONFLITO,
      }),
    ),
  );
  const erro = await api(Metodo.POST, "/api/x").catch((e: unknown) => e);
  expect(erro).toBeInstanceOf(ErroApi);
  expect(erro).toMatchObject({ tipo: TipoErro.OCUPADO, status: CONFLITO, message: "ocupado" });
});
