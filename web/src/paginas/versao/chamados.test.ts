import { expect, it } from "vitest";
import { EstadoChamado } from "../../api/enums";
import type {
  ChamadoConsultado,
  CommitRef,
  VersionStatus,
} from "../../api/tipos";
import { MotivoCommit, filtrarChamados, verChamados } from "./chamados";

const commit = (hash: string, msg: string): CommitRef => ({
  hash_origem: hash,
  parent: "",
  chamado: "",
  commit_date: "2026-01-02T00:00:00Z",
  msg,
});

const PRESENTE = commit("aaaa0001", "base");
const FALTA = commit("bbbb0002", "corrige total\n\ncorpo");
const CONFLITA = commit("cccc0003", "muda layout");
const SUSPEITO = commit("dddd0004", "ajusta texto");
const CAUSADOR = "41";

const chamados: ChamadoConsultado[] = [
  { chamado: "40", estado: EstadoChamado.APLICADO, commits: [PRESENTE] },
  {
    chamado: "41",
    estado: EstadoChamado.PENDENTE,
    commits: [FALTA, CONFLITA, SUSPEITO],
  },
  { chamado: "42", estado: EstadoChamado.PENDENTE, commits: [] },
];

const status: VersionStatus = {
  verde: false,
  estado_integro: true,
  ancestrais: [PRESENTE],
  faltantes: [FALTA, CONFLITA, SUSPEITO],
  conflitantes: [CONFLITA],
  suspeitos_conteudo: [SUSPEITO],
  conflito_causado_por: { [CONFLITA.hash_origem]: [CAUSADOR] },
};

it("verChamados marca falta, conflita e suspeito pelo status", () => {
  const [aplicado, pendente, vazio] = verChamados(chamados, status);
  expect(aplicado?.commits.map((c) => c.motivo)).toEqual([
    MotivoCommit.PRESENTE,
  ]);
  expect(pendente?.commits.map((c) => c.motivo)).toEqual([
    MotivoCommit.FALTA,
    MotivoCommit.CONFLITA,
    MotivoCommit.SUSPEITO,
  ]);
  expect(pendente?.commits[0]?.titulo).toBe("corrige total");
  expect(vazio?.semCommits).toBe(true);
  expect(pendente?.semCommits).toBe(false);
});

it("dependeDe vem de conflito_causado_por", () => {
  const pendente = verChamados(chamados, status)[1];
  expect(pendente?.commits.map((c) => c.dependeDe)).toEqual([
    [],
    [CAUSADOR],
    [],
  ]);
});

it("sem status todos os motivos são null", () => {
  const motivos = verChamados(chamados, null).flatMap((c) =>
    c.commits.map((x) => x.motivo),
  );
  expect(motivos).toEqual([null, null, null, null]);
});

it("filtro por estado e busca por hash, título e número", () => {
  const lista = verChamados(chamados, status);
  const nomes = (estado: EstadoChamado | null, busca: string): string[] =>
    filtrarChamados(lista, estado, busca).map((c) => c.chamado);
  expect(nomes(EstadoChamado.PENDENTE, "")).toEqual(["41", "42"]);
  expect(nomes(null, "AAAA")).toEqual(["40"]);
  expect(nomes(null, "Layout")).toEqual(["41"]);
  expect(nomes(null, "42")).toEqual(["42"]);
  expect(nomes(EstadoChamado.APLICADO, "layout")).toEqual([]);
});
