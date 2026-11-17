import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type JSX,
  type ReactNode,
} from "react";
import { ErroApi, Metodo, api } from "../api/cliente";
import { EstadoExecucao, Operacao, TipoErro } from "../api/enums";
import { acompanhar, type Execucao } from "../api/eventos";
import {
  FaseAtualizacao,
  INICIAL,
  TipoEventoAtualizacao,
  acompanhaOcupado,
  proximo,
  type EstadoAtualizacao,
  type Evento,
  type EventoSimples,
} from "../atualizacao";
import { notificarErro, notificarOk } from "../componentes/notificar";
import { notificarPendencia } from "../componentes/notificarPendencia";
import {
  SEM_EXECUCOES,
  TipoEfeito,
  avisoPendencia,
  concluir,
  iniciar,
  progredir,
  terminar,
  type EstadoExecucoes,
  type Resultado,
} from "../execucoes";
import { lerCaminho } from "../rotas";
import { chaveVersao } from "./chave";

export interface Operacoes {
  execucoes: EstadoExecucoes;
  atualizacao(repo: string, versao: string): EstadoAtualizacao;
  bloqueadas(repo: string): string[];
  verificar(repo: string, versao: string, auditar: boolean): void;
  previa(repo: string, versao: string): void;
  aplicar(repo: string, versao: string, continuar: boolean): void;
  cancelarLote(repo: string, versao: string): void;
  abortar(repo: string, versao: string): void;
  criar(repo: string, numero: string): void;
  fecharResultadoAtualizacao(repo: string, versao: string): void;
  resultado: Resultado | null;
  fecharResultado(): void;
  retomar(repo: string): void;
}

const Contexto = createContext<Operacoes | null>(null);

const urlRepo = (repo: string): string =>
  `/api/repos/${encodeURIComponent(repo)}`;
const urlVersao = (repo: string, versao: string): string =>
  `${urlRepo(repo)}/versoes/${encodeURIComponent(versao)}`;
const pendente = (a: EstadoAtualizacao): boolean =>
  a.fase === FaseAtualizacao.BLOQUEADA || a.fase === FaseAtualizacao.VAZIA;

export function OperacoesProvider({
  children,
  aoNavegar,
}: {
  children: ReactNode;
  aoNavegar: (repo: string, versao?: string) => void;
}): JSX.Element {
  const cliente = useQueryClient();
  const [execucoes, setExecucoes] = useState(SEM_EXECUCOES);
  const execRef = useRef(SEM_EXECUCOES);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [atualizacoes, setAtualizacoes] = useState<
    Readonly<Record<string, EstadoAtualizacao>>
  >({});
  const navegarRef = useRef(aoNavegar);
  navegarRef.current = aoNavegar;
  const despachar = useCallback((k: string, ev: Evento) => {
    setAtualizacoes((a) => ({ ...a, [k]: proximo(a[k] ?? INICIAL, ev) }));
  }, []);
  // O ref é a fonte síncrona (evita duplo acompanhamento); o state só repinta.
  const mudar = useCallback((f: (e: EstadoExecucoes) => EstadoExecucoes) => {
    execRef.current = f(execRef.current);
    setExecucoes(execRef.current);
  }, []);

  const seguir = useCallback(
    async (nome: string, versaoAlvo: string, auditar = false) => {
      const { estado, seguir: abrir } = iniciar(execRef.current, nome, auditar);
      if (!abrir) return;
      mudar(() => estado);
      try {
        const fim = await acompanhar(nome, (p) =>
          mudar((e) => progredir(e, nome, p)),
        );
        if (fim === null) {
          // Nada rodando mais: quem ficou em "aplicando" (409) volta ao que era.
          despachar(chaveVersao(nome, versaoAlvo), {
            tipo: TipoEventoAtualizacao.RECONECTOU,
            execucao: null,
          });
          return;
        }
        despachar(chaveVersao(fim.repo, fim.versao), {
          tipo: TipoEventoAtualizacao.TERMINOU,
          execucao: fim,
        });
        if (
          fim.operacao === Operacao.ABORTAR &&
          fim.estado !== EstadoExecucao.FALHOU
        )
          notificarOk("Atualização abortada");
        if (
          fim.operacao !== Operacao.VERIFICAR &&
          fim.operacao !== Operacao.CRIAR
        )
          void cliente.invalidateQueries({
            queryKey: ["chamados", fim.repo, fim.versao],
          });
        if (fim.estado !== EstadoExecucao.FALHOU)
          void cliente.invalidateQueries({ queryKey: ["versoes", fim.repo] });
        // A URL é a tela atual: o provider vive acima de quem lê a rota.
        const tela = lerCaminho(window.location.pathname);
        const efeito = concluir(execRef.current, fim, tela.repo, tela.versao);
        if (efeito?.tipo === TipoEfeito.ERRO)
          notificarErro(new ErroApi(efeito.tipoErro, efeito.mensagem, 0));
        else if (efeito?.tipo === TipoEfeito.RESULTADO)
          setResultado(efeito.resultado);
        else if (efeito?.tipo === TipoEfeito.NAVEGAR) {
          notificarOk(`Versão ${efeito.versao} criada`);
          navegarRef.current(efeito.repo, efeito.versao);
        } else if (efeito?.tipo === TipoEfeito.AVISAR) {
          const destino = efeito.destino;
          if (destino)
            notificarPendencia(
              chaveVersao(destino.repo, destino.versao),
              efeito.mensagem,
              () => navegarRef.current(destino.repo, destino.versao),
            );
          else notificarOk(efeito.mensagem);
        }
      } catch (erro) {
        notificarErro(erro);
        despachar(chaveVersao(nome, versaoAlvo), {
          tipo: TipoEventoAtualizacao.RECONECTOU,
          execucao: null,
        });
      } finally {
        mudar((e) => terminar(e, nome));
      }
    },
    [cliente, despachar, mudar],
  );

  // Recarregar a página (ou abrir outra aba) retoma os picks abertos e a operação em curso.
  const retomar = useCallback(
    (repo: string) => {
      const url = urlRepo(repo);
      void Promise.all([
        api<Execucao[]>(Metodo.GET, `${url}/pendencias`),
        api<Execucao | null>(Metodo.GET, `${url}/execucao`),
      ])
        .then(([pendencias, e]) => {
          // Pendências antes da atual: uma continuação rodando volta ao bloqueio se falhar.
          for (const x of [...pendencias, ...(e ? [e] : [])])
            despachar(chaveVersao(x.repo, x.versao), {
              tipo: TipoEventoAtualizacao.RECONECTOU,
              execucao: x,
            });
          const versaoNaTela = lerCaminho(window.location.pathname).versao;
          for (const p of pendencias) {
            const aviso = avisoPendencia(p, versaoNaTela);
            if (aviso?.tipo === TipoEfeito.AVISAR && aviso.destino) {
              const { repo: r, versao: v } = aviso.destino;
              notificarPendencia(chaveVersao(r, v), aviso.mensagem, () =>
                navegarRef.current(r, v),
              );
            }
          }
          if (e?.estado === EstadoExecucao.RODANDO) return seguir(repo, e.versao);
        })
        .catch(notificarErro);
    },
    [seguir, despachar],
  );

  const disparar = async (
    repo: string,
    versao: string,
    caminho: string,
    corpo: unknown,
    auditar = false,
  ) => {
    const k = chaveVersao(repo, versao);
    try {
      await api<Execucao>(Metodo.POST, caminho, corpo);
    } catch (erro) {
      // 409: o repo está travado. Se for uma execução do daemon (outra aba), passa a
      // acompanhá-la; se for um processo de fora (CLI, TUI, inscrição), mostra a recusa.
      const ocupadoAqui =
        erro instanceof ErroApi &&
        erro.tipo === TipoErro.OCUPADO &&
        acompanhaOcupado(
          await api<Execucao | null>(
            Metodo.GET,
            `${urlRepo(repo)}/execucao`,
          ).catch(() => null),
        );
      if (!ocupadoAqui) {
        notificarErro(erro);
        despachar(k, {
          tipo: TipoEventoAtualizacao.RECONECTOU,
          execucao: null,
        });
        return;
      }
      despachar(k, { tipo: TipoEventoAtualizacao.OCUPADO });
    }
    await seguir(repo, versao, auditar);
  };

  const atualizacao = (repo: string, versao: string): EstadoAtualizacao =>
    atualizacoes[chaveVersao(repo, versao)] ?? INICIAL;
  const evento = (repo: string, versao: string, tipo: EventoSimples) =>
    despachar(chaveVersao(repo, versao), { tipo });
  const urlAtualizacao = (repo: string, versao: string): string =>
    `${urlVersao(repo, versao)}/atualizacao`;

  const valor: Operacoes = {
    execucoes,
    atualizacao,
    bloqueadas: (repo) => {
      const prefixo = chaveVersao(repo, "");
      return Object.entries(atualizacoes).flatMap(([k, a]) =>
        pendente(a) && k.startsWith(prefixo) ? [k.slice(prefixo.length)] : [],
      );
    },
    verificar: (repo, versao, auditar) =>
      void disparar(
        repo,
        versao,
        `${urlVersao(repo, versao)}/verificacao`,
        { auditar },
        auditar,
      ),
    previa: (repo, versao) => {
      evento(repo, versao, TipoEventoAtualizacao.INICIOU);
      void disparar(repo, versao, `${urlVersao(repo, versao)}/previa`, undefined);
    },
    aplicar: (repo, versao, continuar) => {
      evento(
        repo,
        versao,
        continuar
          ? TipoEventoAtualizacao.CONTINUOU
          : TipoEventoAtualizacao.CONFIRMOU,
      );
      const acao = urlAtualizacao(repo, versao);
      void disparar(
        repo,
        versao,
        continuar ? `${acao}/continuar` : acao,
        continuar
          ? {
              allow_empty:
                atualizacao(repo, versao).fase === FaseAtualizacao.VAZIA,
            }
          : undefined,
      );
    },
    cancelarLote: (repo, versao) => {
      evento(repo, versao, TipoEventoAtualizacao.CANCELOU);
      // Cancelar não desfaz a prévia (ela regravou o snapshot): a lista atrás está velha.
      void cliente.invalidateQueries({ queryKey: ["chamados", repo, versao] });
    },
    abortar: (repo, versao) => {
      evento(repo, versao, TipoEventoAtualizacao.ABORTOU);
      void disparar(
        repo,
        versao,
        `${urlAtualizacao(repo, versao)}/abortar`,
        undefined,
      );
    },
    criar: (repo, numero) =>
      void disparar(repo, numero, `${urlRepo(repo)}/versoes`, { numero }),
    fecharResultadoAtualizacao: (repo, versao) =>
      evento(repo, versao, TipoEventoAtualizacao.FECHOU),
    resultado,
    fecharResultado: () => {
      if (resultado)
        void cliente.invalidateQueries({
          queryKey: ["chamados", resultado.repo, resultado.versao],
        });
      setResultado(null);
    },
    retomar,
  };
  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useOperacoes(): Operacoes {
  const operacoes = useContext(Contexto);
  if (operacoes === null)
    throw new Error("useOperacoes fora do OperacoesProvider");
  return operacoes;
}
