import { ErroApi } from "./cliente";
import { EstadoExecucao, EventoSse, Operacao, TipoErro } from "./enums";

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

const EVENTO_ERRO = "error";
const STATUS_SEM_CONEXAO = 0;

// Resolve com a execução do evento `fim`; o servidor manda `fim` na hora se nada roda.
export function acompanhar(
  repo: string,
  aoProgresso: (p: Progresso) => void,
): Promise<Execucao | null> {
  return new Promise((resolver, rejeitar) => {
    const fonte = new EventSource(
      `/api/repos/${encodeURIComponent(repo)}/execucao/eventos`,
    );
    fonte.addEventListener(EventoSse.PROGRESSO, (e) =>
      aoProgresso(JSON.parse((e as MessageEvent<string>).data) as Progresso),
    );
    // Sem isto o EventSource reconecta sozinho para sempre com o daemon parado.
    fonte.addEventListener(EVENTO_ERRO, () => {
      fonte.close();
      rejeitar(
        new ErroApi(TipoErro.INTERNO, "conexão com o daemon perdida", STATUS_SEM_CONEXAO),
      );
    });
    fonte.addEventListener(EventoSse.FIM, (e) => {
      fonte.close();
      resolver(JSON.parse((e as MessageEvent<string>).data) as Execucao | null);
    });
  });
}
