import type { Locator, Page } from "@playwright/test";

/** Único arquivo que conhece a tela: as specs só falam por estas funções. */

export enum Acao {
  VERIFICAR = "Verificar",
  AUDITAR = "Auditar tag agora",
  ATUALIZAR = "Atualizar",
  CONTINUAR = "Continuar",
  REGISTRAR_VAZIO = "Registrar vazio",
  ABORTAR = "Abortar",
  NOVA_VERSAO = "Nova versão",
  ORFAOS = "Órfãos",
  INSCRICOES = "Inscrições",
  CONFIGURACAO = "Configuração",
  RESOLVER_NA_WEB = "Resolver na web",
  MARCAR_RESOLVIDO = "Marcar resolvido",
}

enum Rotulo {
  REPO = "Repositório",
  VERSAO = "Versão",
}

function caminho(repo: string, versao?: string): string {
  const base = `/r/${encodeURIComponent(repo)}`;
  return versao === undefined ? base : `${base}/v/${encodeURIComponent(versao)}`;
}

export async function abrir(page: Page, repo: string, versao?: string): Promise<void> {
  await page.goto(caminho(repo, versao));
}

export function acao(page: Page, a: Acao): Locator {
  return page.getByRole("button", { name: a, exact: true });
}

export function versaoEscolhida(page: Page): Locator {
  return page.getByRole("combobox", { name: Rotulo.VERSAO, exact: true });
}

export function chamadoListado(page: Page, chamado: string): Locator {
  return page.getByText(`#${chamado}`, { exact: true }).first();
}

/** Abre a lista de repositórios e devolve a opção do nome. */
export async function opcaoRepo(page: Page, nome: string): Promise<Locator> {
  await page.getByRole("combobox", { name: Rotulo.REPO, exact: true }).click();
  return page.getByRole("option", { name: nome, exact: true });
}

export function erro(page: Page): Locator {
  return page.getByRole("alert").first();
}

enum Veredito {
  VERDE = "VERDE",
  PENDENCIAS = "Pendências encontradas",
  AUDITORIA = "Auditoria da tag — snapshot não alterado",
}

export function vereditoVerde(page: Page): Locator {
  return page.getByText(Veredito.VERDE, { exact: true });
}

export function vereditoPendencias(page: Page): Locator {
  return page.getByText(Veredito.PENDENCIAS);
}

export function avisoAuditoria(page: Page): Locator {
  return page.getByText(Veredito.AUDITORIA);
}

export function avisoSemCommits(page: Page, chamado: string): Locator {
  return page.getByText(`Chamados sem commits: ${chamado}`);
}

enum Dialogo {
  ATUALIZACAO = "Atualização",
  ABORTAR = "Abortar cherry-pick",
}

enum Botao {
  APLICAR_LOTE = "Aplicar e publicar",
  ABORTAR = "Abortar",
}

enum Aviso {
  BLOQUEIO = "Atualização bloqueada",
  VAZIO_REGISTRADO = "registrados como commit vazio",
}

const PREFIXO_TITULO_LOTE = "Atualizar";

/** A confirmação do lote, aberta pela prévia do Atualizar. */
export function confirmacaoLote(page: Page, versao: string): Locator {
  return page.getByRole("dialog", { name: `${PREFIXO_TITULO_LOTE} ${versao}`, exact: true });
}

export function chamadoNoLote(page: Page, versao: string, chamado: string): Locator {
  return confirmacaoLote(page, versao).getByText(`#${chamado} ·`);
}

export async function confirmarLote(page: Page, versao: string): Promise<void> {
  await confirmacaoLote(page, versao)
    .getByRole("button", { name: Botao.APLICAR_LOTE, exact: true })
    .click();
}

export function resultadoAtualizacao(page: Page): Locator {
  return page.getByRole("dialog", { name: Dialogo.ATUALIZACAO, exact: true });
}

export async function fecharDialogo(page: Page): Promise<void> {
  await page.keyboard.press("Escape");
}

export function avisoBloqueio(page: Page): Locator {
  return page.getByText(Aviso.BLOQUEIO);
}

export function avisoVazioRegistrado(page: Page): Locator {
  return page.getByText(Aviso.VAZIO_REGISTRADO);
}

export async function confirmarAbortar(page: Page): Promise<void> {
  await page
    .getByRole("dialog", { name: Dialogo.ABORTAR, exact: true })
    .getByRole("button", { name: Botao.ABORTAR, exact: true })
    .click();
}

/** Os lados do bloco em conflito, como o editor web os oferece. */
export enum LadoConflito {
  THEIRS = "Aceitar theirs",
  OURS = "Aceitar ours",
}

/** Abre o arquivo na lista do editor de conflito. */
export async function abrirArquivoDoConflito(page: Page, caminho: string): Promise<void> {
  await page.getByText(caminho, { exact: true }).click();
}

// O "Aceitar" é ação inline do Monaco, sem papel acessível: o texto visível é o contrato.
export async function aceitarLado(page: Page, lado: LadoConflito): Promise<void> {
  await page.getByText(lado, { exact: true }).first().click();
}

enum DialogoModal {
  NOVA_VERSAO = "Nova versão",
}

enum CampoModal {
  NUMERO = "número",
  CHAMADO = "Chamado",
  MOTIVO = "Motivo",
}

enum BotaoModal {
  CRIAR = "Criar e publicar",
  GRAVAR = "Gravar",
}

const dialogoNovaVersao = (page: Page): Locator =>
  page.getByRole("dialog", { name: DialogoModal.NOVA_VERSAO, exact: true });

export function sugestaoDeVersao(page: Page, numero: string): Locator {
  return dialogoNovaVersao(page).getByRole("button", { name: new RegExp(`^${numero}\\b`) });
}

export async function digitarNumeroDaVersao(page: Page, numero: string): Promise<void> {
  await dialogoNovaVersao(page).getByLabel(CampoModal.NUMERO).fill(numero);
}

export function recusaDeVersaoExistente(page: Page, numero: string): Locator {
  return dialogoNovaVersao(page).getByText(`versao ${numero} ja existe`);
}

export function criarEPublicar(page: Page): Locator {
  return dialogoNovaVersao(page).getByRole("button", { name: BotaoModal.CRIAR, exact: true });
}

/** Abre a lista de versões e devolve a opção do número. */
export async function opcaoVersao(page: Page, numero: string): Promise<Locator> {
  await versaoEscolhida(page).click();
  return page.getByRole("option", { name: new RegExp(`^${numero}\\b`) });
}

const dialogoOrfaos = (page: Page, repo: string, versao: string): Locator =>
  page.getByRole("dialog", { name: `Órfãos de ${repo} ${versao}`, exact: true });

export function linhaDoOrfao(page: Page, repo: string, versao: string, assunto: string): Locator {
  return dialogoOrfaos(page, repo, versao).getByRole("row").filter({ hasText: assunto });
}

export async function julgarOrfao(
  page: Page,
  repo: string,
  versao: string,
  assunto: string,
  chamado: string,
  motivo: string,
): Promise<void> {
  const dialogo = dialogoOrfaos(page, repo, versao);
  await linhaDoOrfao(page, repo, versao, assunto).click();
  await dialogo.getByRole("textbox", { name: CampoModal.CHAMADO, exact: true }).fill(chamado);
  await dialogo.getByRole("textbox", { name: CampoModal.MOTIVO, exact: true }).fill(motivo);
  await dialogo.getByRole("button", { name: BotaoModal.GRAVAR, exact: true }).click();
}

enum DialogoInscricoes {
  TITULO = "Inscrições",
}

enum BotaoInscricoes {
  INSCREVER = "Inscrever selecionada",
  REMOVER = "Remover",
}

enum TextoInscricao {
  NUNCA_EXECUTOU = "nunca executou",
}

const dialogoInscricoes = (page: Page): Locator =>
  page.getByRole("dialog", { name: DialogoInscricoes.TITULO, exact: true });

export function linhaDaInscricao(page: Page, versao: string): Locator {
  return dialogoInscricoes(page).getByRole("row").filter({ hasText: versao });
}

export async function inscreverSelecionada(page: Page): Promise<void> {
  await dialogoInscricoes(page)
    .getByRole("button", { name: BotaoInscricoes.INSCREVER, exact: true })
    .click();
}

export async function removerInscricao(page: Page, versao: string): Promise<void> {
  await linhaDaInscricao(page, versao)
    .getByRole("button", { name: BotaoInscricoes.REMOVER, exact: true })
    .click();
}

export function inscricaoNuncaExecutou(page: Page, versao: string): Locator {
  return linhaDaInscricao(page, versao).getByText(TextoInscricao.NUNCA_EXECUTOU);
}

/** A notificação da rodada: título "versão · repo". */
export function avisoDaRodada(page: Page, versao: string, repo: string): Locator {
  return page.getByText(`${versao} · ${repo}`, { exact: true });
}

enum DialogoConfig {
  TITULO = "Configuração",
}

enum BotaoConfig {
  TESTAR = "Testar",
  SALVAR = "Salvar",
}

export enum CampoRepo {
  PISO = "Piso de versão",
}

const dialogoConfig = (page: Page): Locator =>
  page.getByRole("dialog", { name: DialogoConfig.TITULO, exact: true });

/** Vai à seção pelo nome na lateral (o do repo, para as seções de repositório). */
export async function abrirSecaoDaConfiguracao(page: Page, nome: string): Promise<void> {
  await dialogoConfig(page)
    .getByRole("navigation")
    .getByRole("button", { name: nome })
    .click();
}

export function campoDaConfiguracao(page: Page, campo: CampoRepo): Locator {
  return dialogoConfig(page).getByLabel(campo);
}

export async function testarSecao(page: Page): Promise<void> {
  await dialogoConfig(page)
    .getByRole("button", { name: BotaoConfig.TESTAR, exact: true })
    .click();
}

export function resultadoDoTeste(page: Page, nome: string): Locator {
  return dialogoConfig(page).getByText(`✓ ${nome}`, { exact: true });
}

export async function salvarConfiguracao(page: Page): Promise<void> {
  await dialogoConfig(page)
    .getByRole("button", { name: BotaoConfig.SALVAR, exact: true })
    .click();
}

enum AvisoConfig {
  SALVA = "Configuração salva",
}

export function avisoConfiguracaoSalva(page: Page): Locator {
  return page.getByText(AvisoConfig.SALVA, { exact: true });
}

enum AvisoOcupado {
  RECUSA = "ocupado por outra operação",
}

export function avisoRepoOcupado(page: Page): Locator {
  return page.getByText(AvisoOcupado.RECUSA);
}
