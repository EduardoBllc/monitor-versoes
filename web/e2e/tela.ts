import type { Locator, Page } from "@playwright/test";

/**
 * Único arquivo que conhece a tela: seletores e sequências de interação. As specs só
 * chamam estas funções e asserem desfechos.
 */

export enum Acao {
  VERIFICAR = "Verificar",
  AUDITAR = "Auditar tag agora",
  ATUALIZAR = "Atualizar",
  CONTINUAR = "Continuar",
  REGISTRAR_VAZIO = "Registrar vazio",
  ABORTAR = "Abortar",
  NOVA_VERSAO = "Nova versão",
  ORFAOS = "Órfãos",
  CONFIGURACAO = "Configuração",
  RESOLVER_NA_WEB = "Resolver na web",
  MARCAR_RESOLVIDO = "Marcar resolvido",
}

/** Os lados do bloco em conflito, como o editor web os oferece. */
export enum LadoConflito {
  THEIRS = "Aceitar theirs",
}

enum Campo {
  NUMERO = "número",
  CHAMADO = "Chamado",
  MOTIVO = "Motivo",
  PISO = "Piso de versão",
}

/** Títulos dos diálogos; um prefixo leva o resto do título depois de um espaço. */
enum Dialogo {
  ATUALIZACAO = "Atualização",
  ABORTAR = "Abortar cherry-pick",
  PREFIXO_LOTE = "Atualizar",
  NOVA_VERSAO = "Nova versão",
  PREFIXO_ORFAOS = "Órfãos de",
  RESULTADO = "Resultado",
}

enum Botao {
  APLICAR_LOTE = "Aplicar e publicar",
  ABORTAR = "Abortar",
  CRIAR = "Criar e publicar",
  GRAVAR = "Gravar",
  INSCREVER = "Inscrever",
  REMOVER = "Remover",
  TESTAR = "Testar",
  SALVAR = "Salvar",
}

/** A trilha no topo: Início › repo › versão. */
enum Trilha {
  NOME = "Trilha",
  INICIO = "Início",
}

export enum Veredito {
  VERDE = "VERDE",
  PENDENCIAS = "Pendências encontradas",
}

enum Aviso {
  AUDITORIA = "Auditoria da tag — snapshot não alterado",
  PREFIXO_SEM_COMMITS = "Chamados sem commits:",
  BLOQUEIO = "Atualização bloqueada",
  VAZIO_REGISTRADO = "registrados como commit vazio",
  INICIO_VERSAO_EXISTENTE = "versao",
  FIM_VERSAO_EXISTENTE = "ja existe",
  PREFIXO_JULGADO = "pertence a",
  NUNCA_EXECUTOU = "nunca executou",
  PREFIXO_TESTE_OK = "✓",
  CONFIG_SALVA = "Configuração salva",
  REPO_OCUPADO = "ocupado por outra operação",
}

enum Regiao {
  INSCRICAO = "Inscrição",
  PRECISA_DE_VOCE = "Precisa de você",
}

/** Peças do texto das linhas: "#chamado · assunto", "versão · repo". */
enum Formato {
  PREFIXO_CHAMADO = "#",
  SEPARADOR = "·",
}

// Disparo do daemon (a cada 60 s, decisão 041) + consulta da web (15 s) + folga.
const ESPERA_AVISO_DA_RODADA_MS = 90_000;

const literal = (texto: string): string => texto.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Opção ou botão cujo nome começa pelo número da versão. */
const comecaCom = (numero: string): RegExp => new RegExp(`^${literal(numero)}\\b`);

/** Trecho de texto com a caixa exata, como o `toContainText`. */
const trecho = (texto: string): RegExp => new RegExp(literal(texto));

function caminho(repo: string, versao?: string): string {
  const base = `/r/${encodeURIComponent(repo)}`;
  return versao === undefined ? base : `${base}/v/${encodeURIComponent(versao)}`;
}

const dialogo = (page: Page, titulo: string): Locator =>
  page.getByRole("dialog", { name: titulo, exact: true });

const trilha = (page: Page): Locator =>
  page.getByRole("navigation", { name: Trilha.NOME, exact: true });

/** Volta ao Início pela trilha, de qualquer página. */
export async function voltarAoInicio(page: Page): Promise<void> {
  await trilha(page).getByRole("link", { name: Trilha.INICIO, exact: true }).click();
}

/** Da página da versão, sobe ao repo pelo passo dele na trilha. */
async function irAoRepoPelaTrilha(page: Page, repo: string): Promise<void> {
  await trilha(page).getByRole("link", { name: repo, exact: true }).click();
}

const botao = (raiz: Page | Locator, nome: Botao): Locator =>
  raiz.getByRole("button", { name: nome, exact: true });

export async function abrir(page: Page, repo: string, versao?: string): Promise<void> {
  await page.goto(caminho(repo, versao));
}

export function acao(page: Page, a: Acao): Locator {
  return page.getByRole("button", { name: a, exact: true });
}

export async function fecharDialogo(page: Page): Promise<void> {
  await page.keyboard.press("Escape");
}

// Navegação

export function tituloDaVersao(page: Page): Locator {
  return page.getByRole("heading", { level: 1 });
}

/** O conteúdo da página, fora dos diálogos. */
const pagina = (page: Page): Locator => page.getByRole("main");

export function chamadoListado(page: Page, chamado: string): Locator {
  return pagina(page).getByText(`${Formato.PREFIXO_CHAMADO}${chamado}`, { exact: true });
}

/** Volta ao início pela trilha e devolve o repo listado (link, ou item indisponível). */
export async function repoNaInicio(page: Page, nome: string): Promise<Locator> {
  await voltarAoInicio(page);
  return page.getByRole("link", { name: nome, exact: true });
}

/** Da página da versão, sobe ao repo e devolve a versão na lista dele. */
export async function versaoNoRepo(page: Page, repo: string, numero: string): Promise<Locator> {
  await irAoRepoPelaTrilha(page, repo);
  return page.getByRole("link", { name: comecaCom(numero) });
}

/**
 * Com edição pendente no editor, sai pela trilha para o início, aceitando ou recusando
 * a confirmação do navegador.
 */
export async function navegarComEdicaoPendente(page: Page, aceitar: boolean): Promise<void> {
  page.once("dialog", (d) => void (aceitar ? d.accept() : d.dismiss()));
  await voltarAoInicio(page);
}

export function erro(page: Page): Locator {
  return page.getByRole("alert").first();
}

// Vereditos e avisos: os do resultado da verificação recém-rodada.

const resultado = (page: Page): Locator => dialogo(page, Dialogo.RESULTADO);

export function vereditoVerde(page: Page): Locator {
  return resultado(page).getByText(Veredito.VERDE, { exact: true });
}

export function vereditoPendencias(page: Page): Locator {
  return resultado(page).getByText(Veredito.PENDENCIAS);
}

/** O veredito gravado que a página da versão mostra, fora do diálogo do resultado. */
export function vereditoDaPagina(page: Page, veredito: Veredito): Locator {
  return pagina(page).getByText(veredito, { exact: true });
}

export function avisoAuditoria(page: Page): Locator {
  return resultado(page).getByText(Aviso.AUDITORIA);
}

export function avisoSemCommits(page: Page, chamado: string): Locator {
  return resultado(page).getByText(`${Aviso.PREFIXO_SEM_COMMITS} ${chamado}`);
}

export function avisoBloqueio(page: Page): Locator {
  return page.getByText(Aviso.BLOQUEIO);
}

export function avisoVazioRegistrado(page: Page): Locator {
  return page.getByText(Aviso.VAZIO_REGISTRADO);
}

export function avisoRepoOcupado(page: Page): Locator {
  return page.getByText(Aviso.REPO_OCUPADO);
}

// Atualizar

const confirmacaoLote = (page: Page, versao: string): Locator =>
  dialogo(page, `${Dialogo.PREFIXO_LOTE} ${versao}`);

/** Pede o Atualizar e para na prévia do lote, sem aplicar. */
export async function previaDoLote(page: Page): Promise<void> {
  await acao(page, Acao.ATUALIZAR).click();
}

export function chamadoNoLote(page: Page, versao: string, chamado: string): Locator {
  return confirmacaoLote(page, versao).getByText(
    `${Formato.PREFIXO_CHAMADO}${chamado} ${Formato.SEPARADOR}`,
  );
}

export async function confirmarLote(page: Page, versao: string): Promise<void> {
  await botao(confirmacaoLote(page, versao), Botao.APLICAR_LOTE).click();
}

/** Atualiza a versão aplicando o lote inteiro. */
export async function atualizarLote(page: Page, versao: string): Promise<void> {
  await previaDoLote(page);
  await confirmarLote(page, versao);
}

export function resultadoAtualizacao(page: Page): Locator {
  return dialogo(page, Dialogo.ATUALIZACAO);
}

/** Continua o bloqueio cuja resolução zerou o diff, registrando o commit vazio. */
export async function continuarComoVazio(page: Page): Promise<void> {
  await acao(page, Acao.CONTINUAR).click();
  await acao(page, Acao.REGISTRAR_VAZIO).click();
}

export async function abortarBloqueio(page: Page): Promise<void> {
  await acao(page, Acao.ABORTAR).click();
  await botao(dialogo(page, Dialogo.ABORTAR), Botao.ABORTAR).click();
}

/** Resolve um bloco do arquivo no editor web, sem marcá-lo resolvido. */
export async function resolverBlocoNaWeb(
  page: Page,
  arquivo: string,
  lado: LadoConflito,
): Promise<void> {
  await acao(page, Acao.RESOLVER_NA_WEB).click();
  await page.getByText(arquivo, { exact: true }).click();
  // O "Aceitar" é ação inline do Monaco, sem papel acessível: o texto visível é o contrato.
  await page.getByText(lado, { exact: true }).first().click();
}

/** Resolve o arquivo no editor web e o marca resolvido. */
export async function resolverConflitoNaWeb(
  page: Page,
  arquivo: string,
  lado: LadoConflito,
): Promise<void> {
  await resolverBlocoNaWeb(page, arquivo, lado);
  await acao(page, Acao.MARCAR_RESOLVIDO).click();
}

/** O editor de conflito está aberto. */
export function editorDeConflito(page: Page): Locator {
  return acao(page, Acao.MARCAR_RESOLVIDO);
}

// Nova versão

const dialogoNovaVersao = (page: Page): Locator => dialogo(page, Dialogo.NOVA_VERSAO);

/** Da página da versão, sobe ao repo e abre a nova versão. */
export async function abrirNovaVersao(page: Page, repo: string): Promise<void> {
  await irAoRepoPelaTrilha(page, repo);
  await acao(page, Acao.NOVA_VERSAO).click();
}

export function sugestaoDeVersao(page: Page, numero: string): Locator {
  return dialogoNovaVersao(page).getByRole("button", { name: comecaCom(numero) });
}

/** Abre a nova versão e digita o número, sem criar. */
export async function proporNumeroDaVersao(
  page: Page,
  repo: string,
  numero: string,
): Promise<void> {
  await abrirNovaVersao(page, repo);
  await dialogoNovaVersao(page).getByLabel(Campo.NUMERO).fill(numero);
}

export function recusaDeVersaoExistente(page: Page, numero: string): Locator {
  return dialogoNovaVersao(page).getByText(
    `${Aviso.INICIO_VERSAO_EXISTENTE} ${numero} ${Aviso.FIM_VERSAO_EXISTENTE}`,
  );
}

export function criarEPublicar(page: Page): Locator {
  return botao(dialogoNovaVersao(page), Botao.CRIAR);
}

/** Cria a versão escolhendo-a entre as sugestões e espera a web abri-la. */
export async function criarVersaoSugerida(
  page: Page,
  repo: string,
  numero: string,
): Promise<void> {
  await abrirNovaVersao(page, repo);
  await sugestaoDeVersao(page, numero).click();
  await criarEPublicar(page).click();
  await tituloDaVersao(page).filter({ hasText: comecaCom(numero) }).waitFor();
}

// Órfãos

const dialogoOrfaos = (page: Page, repo: string, versao: string): Locator =>
  dialogo(page, `${Dialogo.PREFIXO_ORFAOS} ${repo} ${versao}`);

export async function abrirOrfaos(page: Page): Promise<void> {
  await acao(page, Acao.ORFAOS).click();
}

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
  const d = dialogoOrfaos(page, repo, versao);
  await linhaDoOrfao(page, repo, versao, assunto).click();
  await d.getByRole("textbox", { name: Campo.CHAMADO, exact: true }).fill(chamado);
  await d.getByRole("textbox", { name: Campo.MOTIVO, exact: true }).fill(motivo);
  await botao(d, Botao.GRAVAR).click();
}

/** O órfão julgado: esta tela mantém a linha, com o chamado e o motivo. */
export function orfaoJulgado(
  page: Page,
  repo: string,
  versao: string,
  assunto: string,
  chamado: string,
  motivo: string,
): Locator {
  return linhaDoOrfao(page, repo, versao, assunto)
    .filter({ hasText: trecho(`${Aviso.PREFIXO_JULGADO} ${chamado}`) })
    .filter({ hasText: trecho(motivo) });
}

// Inscrições: o bloco da inscrição na página da versão.

const blocoInscricao = (page: Page): Locator =>
  page.getByRole("region", { name: Regiao.INSCRICAO, exact: true });

/** Inscreve a versão aberta nas rodadas agendadas. */
export async function inscrever(page: Page): Promise<void> {
  await botao(blocoInscricao(page), Botao.INSCREVER).click();
}

/** A versão aberta está inscrita: o bloco oferece remover. */
export function inscricaoAtiva(page: Page): Locator {
  return botao(blocoInscricao(page), Botao.REMOVER);
}

export async function removerInscricao(page: Page): Promise<void> {
  await inscricaoAtiva(page).click();
}

export function inscricaoNuncaExecutou(page: Page): Locator {
  return blocoInscricao(page).getByText(Aviso.NUNCA_EXECUTOU);
}

/** A notificação da rodada: título "versão · repo". */
export function avisoDaRodada(page: Page, versao: string, repo: string): Locator {
  return page.getByText(`${versao} ${Formato.SEPARADOR} ${repo}`, { exact: true });
}

/** Espera a web notar a rodada, que esta tela só consulta de tempos em tempos. */
export async function esperarAvisoDaRodada(
  page: Page,
  versao: string,
  repo: string,
): Promise<void> {
  await avisoDaRodada(page, versao, repo).waitFor({ timeout: ESPERA_AVISO_DA_RODADA_MS });
}

// Configuração

/** Abre a configuração na seção do repo e devolve o campo do piso. */
export async function pisoNaConfiguracao(page: Page, repo: string): Promise<Locator> {
  await page.getByRole("link", { name: Acao.CONFIGURACAO, exact: true }).click();
  await pagina(page).getByRole("navigation").getByRole("button", { name: repo }).click();
  return pagina(page).getByLabel(Campo.PISO);
}

/** Muda o piso do repo e pede o teste da seção, sem salvar. */
export async function editarPisoETestar(page: Page, repo: string, piso: string): Promise<void> {
  await (await pisoNaConfiguracao(page, repo)).fill(piso);
  await botao(pagina(page), Botao.TESTAR).click();
}

export function resultadoDoTeste(page: Page, nome: string): Locator {
  return pagina(page).getByText(`${Aviso.PREFIXO_TESTE_OK} ${nome}`, { exact: true });
}

export async function salvarConfiguracao(page: Page): Promise<void> {
  await botao(pagina(page), Botao.SALVAR).click();
}

export function avisoConfiguracaoSalva(page: Page): Locator {
  return page.getByText(Aviso.CONFIG_SALVA, { exact: true });
}

// Início e página do repo

enum TextoLinha {
  INDISPONIVEL = "indisponível",
  VERIFICADA = "verificada há",
  ATUALIZADA = "atualizada há",
  RESOLVER = "Resolver",
  BLOQUEADA = "bloqueada",
}

/** Na home, cada repo é uma região com o nome dele. */
const regiaoDoRepo = (page: Page, repo: string): Locator =>
  page.getByRole("region", { name: repo, exact: true });

/** A linha da versão nas listas da home e do repo. */
const linhaDaVersao = (page: Page, numero: string): Locator =>
  page
    .getByRole("listitem")
    .filter({ has: page.getByRole("link", { name: numero, exact: true }) });

const pendenciaNaInicio = (page: Page, versao: string): Locator =>
  page
    .getByRole("region", { name: Regiao.PRECISA_DE_VOCE, exact: true })
    .getByRole("listitem")
    .filter({ has: page.getByText(versao, { exact: true }) });

export async function abrirInicio(page: Page): Promise<void> {
  await page.goto("/");
}

export async function subirAoRepo(page: Page, repo: string): Promise<void> {
  await irAoRepoPelaTrilha(page, repo);
}

export function versaoNaInicio(page: Page, repo: string, numero: string): Locator {
  return regiaoDoRepo(page, repo).getByRole("link", { name: numero, exact: true });
}

export function repoIndisponivelNaInicio(page: Page, repo: string): Locator {
  return regiaoDoRepo(page, repo).getByText(TextoLinha.INDISPONIVEL);
}

export function bloqueioNaInicio(page: Page, versao: string): Locator {
  return pendenciaNaInicio(page, versao);
}

/** Pelo "Precisa de você" da home, vai à versão bloqueada. */
export async function resolverPelaInicio(page: Page, versao: string): Promise<void> {
  await pendenciaNaInicio(page, versao)
    .getByRole("link", { name: TextoLinha.RESOLVER, exact: true })
    .click();
}

export function verificacaoNaLinha(page: Page, numero: string): Locator {
  return linhaDaVersao(page, numero).getByText(trecho(TextoLinha.VERIFICADA));
}

export function bloqueioNaLinha(page: Page, numero: string): Locator {
  return linhaDaVersao(page, numero).getByText(TextoLinha.BLOQUEADA, { exact: true });
}

/** O aviso de repo sem checkout no conteúdo da página aberta. */
export function avisoIndisponivel(page: Page): Locator {
  return pagina(page).getByText(trecho(TextoLinha.INDISPONIVEL));
}

export function atualizacaoNaLinha(page: Page, numero: string): Locator {
  return linhaDaVersao(page, numero).getByText(trecho(TextoLinha.ATUALIZADA));
}

// Chamados da versão

/** Motivo de um commit do chamado, como a lista da página o mostra. */
export enum MotivoCommit {
  FALTA = "falta",
}

const TAMANHO_HASH = 8;

export async function expandirChamado(page: Page, chamado: string): Promise<void> {
  await chamadoListado(page, chamado).click();
}

/** O commit listado sob o chamado expandido, pelo hash curto e com o motivo. */
export function commitDoChamado(page: Page, hash: string, motivo: MotivoCommit): Locator {
  return pagina(page)
    .getByRole("row")
    .filter({ hasText: hash.slice(0, TAMANHO_HASH) })
    .filter({ hasText: trecho(motivo) });
}

// Paleta ⌘K

/** Abre a paleta pelo atalho, digita a busca e escolhe o primeiro resultado que a contém. */
export async function saltarPelaPaleta(page: Page, busca: string): Promise<void> {
  await page.keyboard.press("Control+K");
  const paleta = page.getByRole("dialog");
  await paleta.getByRole("textbox").fill(busca);
  // Cada resultado da paleta é um botão; o índice chega por rede e o clique espera por ele.
  await paleta.getByRole("button", { name: trecho(busca) }).first().click();
}
