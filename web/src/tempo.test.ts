import { expect, it } from "vitest";
import { ha } from "./tempo";

const AGORA = Date.parse("2026-01-01T12:00:00Z");
const MINUTO_MS = 60_000;
const MINUTOS = 3;

it("há conta na maior unidade que cabe", () => {
  expect(ha(new Date(AGORA - MINUTOS * MINUTO_MS).toISOString(), AGORA)).toBe(
    `há ${MINUTOS} minutos`,
  );
});

it("menos de um segundo é há instantes", () => {
  expect(ha(new Date(AGORA).toISOString(), AGORA)).toBe("há instantes");
});
