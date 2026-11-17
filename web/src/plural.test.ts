import { expect, it } from "vitest";
import { plural } from "./plural";

const UM = 1;
const DOIS = 2;
const NENHUM = 0;

it("um leva o singular; zero e mais de um, o plural", () => {
  expect(plural(UM, "faltante", "faltantes")).toBe("1 faltante");
  expect(plural(DOIS, "versão liberada", "versões liberadas")).toBe("2 versões liberadas");
  expect(plural(NENHUM, "conflito", "conflitos")).toBe("0 conflitos");
});
