import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EstadoExecucao, EventoSse, Operacao } from "./enums";
import { acompanhar, type Execucao } from "./eventos";

type Ouvinte = (e: MessageEvent<string>) => void;

class FalsoEventSource {
  static ultimo: FalsoEventSource;
  ouvintes = new Map<string, Ouvinte>();
  fechado = false;
  constructor(readonly url: string) {
    FalsoEventSource.ultimo = this;
  }
  addEventListener(nome: string, ouvinte: Ouvinte) {
    this.ouvintes.set(nome, ouvinte);
  }
  close() {
    this.fechado = true;
  }
  emitir(nome: EventoSse, dados: unknown) {
    this.ouvintes.get(nome)?.({ data: JSON.stringify(dados) } as MessageEvent<string>);
  }
}

const EXECUCAO: Execucao = {
  id: "abc",
  repo: "meu-repo",
  versao: "14.0.0",
  operacao: Operacao.VERIFICAR,
  estado: EstadoExecucao.CONCLUIDA,
  progresso: null,
  resultado: null,
  erro: null,
};

beforeEach(() => vi.stubGlobal("EventSource", FalsoEventSource));
afterEach(() => vi.unstubAllGlobals());

it("progresso chama o callback e fim resolve e fecha", async () => {
  const vistos: unknown[] = [];
  const promessa = acompanhar("meu-repo", (p) => vistos.push(p));
  const fonte = FalsoEventSource.ultimo;
  const progresso = { fase: "buscando", feito: 1, total: 2 };
  fonte.emitir(EventoSse.PROGRESSO, progresso);
  fonte.emitir(EventoSse.FIM, EXECUCAO);
  expect(await promessa).toEqual(EXECUCAO);
  expect(vistos).toEqual([progresso]);
  expect(fonte.fechado).toBe(true);
});

it("fim como primeiro evento resolve na hora", async () => {
  const promessa = acompanhar("meu-repo", () => undefined);
  FalsoEventSource.ultimo.emitir(EventoSse.FIM, EXECUCAO);
  expect(await promessa).toEqual(EXECUCAO);
});
