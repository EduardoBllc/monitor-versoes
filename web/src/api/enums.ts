// Espelho dos enums do Python; valor novo no motor exige atualizar aqui.
export enum AtualizarStatus {
  DONE = 0,
  BLOCKED = 1,
  VAZIO = 2,
}

export enum Operacao {
  VERIFICAR = "verificar",
  PREVIA = "previa",
  ATUALIZAR = "atualizar",
  CONTINUAR = "continuar",
  ABORTAR = "abortar",
  CRIAR = "criar",
}

export enum EstadoExecucao {
  RODANDO = "rodando",
  CONCLUIDA = "concluida",
  FALHOU = "falhou",
}

export enum TipoErro {
  ENTRADA = "entrada",
  NAO_ENCONTRADO = "nao_encontrado",
  RECUSA = "recusa",
  BACKEND = "backend",
  RESPOSTA = "resposta",
  MOTOR = "motor",
  OCUPADO = "ocupado",
  DESATUALIZADO = "desatualizado",
  INTERNO = "interno",
}

export enum TipoArquivo {
  CONTEUDO = "conteudo",
  MODIFICADO_APAGADO = "modificado_apagado",
  OUTRO = "outro",
}

export enum Desfecho {
  APLICOU = "aplicou",
  NADA = "nada",
  BLOQUEADA = "bloqueada",
  PULADA = "pulada",
  ERRO = "erro",
  ENCERRADA = "encerrada",
}

export enum EventoSse {
  PROGRESSO = "progresso",
  FIM = "fim",
}

export function assertNever(valor: never): never {
  throw new Error(`valor inesperado: ${String(valor)}`);
}

export enum EstadoChamado {
  APLICADO = "aplicado",
}

export enum Escopo {
  GERAL = "geral",
  REPO = "repo",
  AMBIENTE = "ambiente",
}

export enum TipoCampo {
  TEXTO = "texto",
  INTEIRO = "inteiro",
  ESCOLHA = "escolha",
}

export enum GrupoPlugin {
  TAREFAS = "monitor_versoes.tarefas",
  PRS = "monitor_versoes.prs",
  ESQUEMAS = "monitor_versoes.esquemas",
  ATRIBUICOES = "monitor_versoes.atribuicoes",
  SUGESTAO = "monitor_versoes.sugestao",
}

export enum AcaoAlteracao {
  DEFINIR = "definir",
  REMOVER = "remover",
  CRIAR_REPO = "criar_repo",
  REMOVER_REPO = "remover_repo",
}

export enum PecaTestavel {
  PRS = "prs",
  TAREFAS = "tarefas",
  REPO = "repo",
}

export enum EstadoTeste {
  OK = "OK",
  FALHA = "FALHA",
  NAO_VERIFICADA = "não verificada",
  NAO_CONFIGURADO = "não configurado",
  AVISO = "aviso",
}

export enum Tabela {
  VERSAO = "versao",
  LIBERACAO = "liberacao",
  BRANCHES = "branches",
  REFERENCIA = "referencia",
  TAREFAS = "tarefas",
  PRS = "prs",
  SUGESTAO = "sugestao",
}

export enum Chave {
  ESQUEMA = "esquema",
  ATRIBUICAO = "atribuicao",
  TAG = "tag",
  VERSAO = "versao",
  PRINCIPAL = "principal",
  PADRAO = "padrao",
  FONTE = "fonte",
  PISO = "piso",
  PROVEDOR = "provedor",
}

export enum VarAmbiente {
  DATABASE_SQLITE_PATH = "DATABASE_SQLITE_PATH",
  WORKTREES_MANTIDAS = "WORKTREES_MANTIDAS",
}

export enum TipoOrigem {
  GIT = "git",
  INDICE = "índice",
  EMBUTIDO = "embutido",
  LOCAL = "local",
}
