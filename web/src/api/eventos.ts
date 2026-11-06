import { EstadoExecucao, EventoSse, Operacao, type TipoErro } from "./enums";

export interface Progresso {
  fase: string;
  feito: number;
  total: number;
}

export interface Execucao {
  id: string;
  repo: string;
  versao: string;
  operacao: Operacao;
  estado: EstadoExecucao;
  progresso: Progresso | null;
  resultado: unknown;
  erro: { tipo: TipoErro; mensagem: string } | null;
}

// Resolve com a execução do evento `fim`; o servidor manda `fim` na hora se nada roda.
export function acompanhar(
  repo: string,
  aoProgresso: (p: Progresso) => void,
): Promise<Execucao | null> {
  return new Promise((resolver) => {
    const fonte = new EventSource(
      `/api/repos/${encodeURIComponent(repo)}/execucao/eventos`,
    );
    fonte.addEventListener(EventoSse.PROGRESSO, (e) =>
      aoProgresso(JSON.parse((e as MessageEvent<string>).data) as Progresso),
    );
    fonte.addEventListener(EventoSse.FIM, (e) => {
      fonte.close();
      resolver(JSON.parse((e as MessageEvent<string>).data) as Execucao | null);
    });
  });
}
