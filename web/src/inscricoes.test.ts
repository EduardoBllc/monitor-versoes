import { expect, it } from "vitest";
import { Desfecho } from "./api/enums";
import type { InscricaoVista } from "./api/tipos";
import { CorAviso, avisos, rodadasNovas } from "./inscricoes";

const HORA_ANTES = "2026-01-01T10:00:00Z";
const HORA_DEPOIS = "2026-01-01T10:15:00Z";

const inscricao = (
  ultima: Partial<NonNullable<InscricaoVista["ultima"]>> | null,
): InscricaoVista => ({
  repo: "app",
  versao: "1.2.0",
  intervalo: "1h",
  ultima:
    ultima === null
      ? null
      : {
          hora: HORA_DEPOIS,
          desfecho: Desfecho.NADA,
          desfecho_aviso: Desfecho.NADA,
          vermelhos: [],
          mensagem: "",
          ...ultima,
        },
});

it("sem lista anterior não avisa nada", () => {
  expect(
    avisos(undefined, [inscricao({ desfecho: Desfecho.APLICOU })]),
  ).toEqual([]);
});

it("primeira execução que aplicou avisa", () => {
  const r = avisos(
    [inscricao(null)],
    [inscricao({ desfecho: Desfecho.APLICOU })],
  );
  expect(r).toHaveLength(1);
  expect(r[0]?.titulo).toBe("1.2.0 · app");
  expect(r[0]?.cor).toBe(CorAviso.VERDE);
});

it("bloqueada avisa com a mensagem", () => {
  const r = avisos(
    [inscricao({ hora: HORA_ANTES })],
    [inscricao({ desfecho: Desfecho.BLOQUEADA, mensagem: "x.py" })],
  );
  expect(r).toHaveLength(1);
  expect(r[0]?.cor).toBe(CorAviso.LARANJA);
  expect(r[0]?.mensagem).toContain("x.py");
});

it("erro repetido não avisa de novo", () => {
  const antes = inscricao({ hora: HORA_ANTES, desfecho_aviso: Desfecho.ERRO });
  const depois = inscricao({ desfecho: Desfecho.ERRO, mensagem: "falhou" });
  expect(avisos([antes], [depois])).toEqual([]);
});

it("erro após outro desfecho avisa com a mensagem", () => {
  const antes = inscricao({ hora: HORA_ANTES });
  const depois = inscricao({ desfecho: Desfecho.ERRO, mensagem: "falhou" });
  const r = avisos([antes], [depois]);
  expect(r).toHaveLength(1);
  expect(r[0]?.cor).toBe(CorAviso.VERMELHO);
  expect(r[0]?.mensagem).toContain("falhou");
});

it("nada com vermelho novo avisa só dos vermelhos", () => {
  const antes = inscricao({ hora: HORA_ANTES, vermelhos: ["A-1"] });
  const depois = inscricao({ vermelhos: ["A-1", "B-2"] });
  const r = avisos([antes], [depois]);
  expect(r).toHaveLength(1);
  expect(r[0]?.mensagem).toContain("B-2");
  expect(r[0]?.mensagem).not.toContain("A-1");
});

it("inscrição ausente em depois ou hora igual não avisa", () => {
  const antes = inscricao({ desfecho: Desfecho.APLICOU });
  expect(avisos([antes], [])).toEqual([]);
  expect(avisos([antes], [antes])).toEqual([]);
});

it("rodada nova é a inscrição cuja última hora mudou", () => {
  const nova = inscricao({ hora: HORA_DEPOIS });
  const parada = { ...inscricao({ hora: HORA_ANTES }), versao: "1.3.0" };
  expect(rodadasNovas([inscricao({ hora: HORA_ANTES }), parada], [nova, parada])).toEqual([nova]);
});

it("sem lista anterior ou sem rodada não há rodada nova", () => {
  expect(rodadasNovas(undefined, [inscricao({})])).toEqual([]);
  expect(rodadasNovas([inscricao(null)], [inscricao(null)])).toEqual([]);
});
