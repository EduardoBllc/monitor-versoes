import { RecursoApi, expect, git, rotaApi, test, type Manifesto } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  abortarBloqueio,
  abrir,
  acao,
  atualizarLote,
  avisoBloqueio,
  avisoVazioRegistrado,
  chamadoNoLote,
  confirmarLote,
  continuarComoVazio,
  fecharDialogo,
  previaDoLote,
  resultadoAtualizacao,
  vereditoVerde,
} from "./tela";

const TRAILER_CHERRY_PICK = "cherry picked from commit";

const pontaDaBranch = (manifesto: Manifesto, versao: string): string =>
  git(manifesto, manifesto.clone, "rev-parse", versao);

test("atualizar aplica o lote com trailer e a versão fica verde", async ({
  page,
  manifesto,
}) => {
  const versao = manifesto.versoes[PapelVersao.FALTANTES];
  await abrir(page, manifesto.repo, versao);
  await previaDoLote(page);
  await expect(
    chamadoNoLote(page, versao, manifesto.chamados[PapelVersao.FALTANTES]),
  ).toBeVisible();
  await confirmarLote(page, versao);
  await expect(resultadoAtualizacao(page)).toBeVisible();
  await fecharDialogo(page);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoVerde(page)).toBeVisible();
  expect(git(manifesto, manifesto.clone, "log", versao)).toContain(
    TRAILER_CHERRY_PICK,
  );
});

test("pick sem alteração entra como commit vazio e a versão fica verde", async ({
  page,
  manifesto,
}) => {
  // O motor registra sozinho o pick que sai vazio no lote: o registro manual só existe
  // quando uma resolução de conflito zera o diff (teste seguinte).
  const versao = manifesto.versoes[PapelVersao.VAZIO];
  await abrir(page, manifesto.repo, versao);
  await atualizarLote(page, versao);
  await expect(avisoVazioRegistrado(page)).toBeVisible();
  await fecharDialogo(page);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoVerde(page)).toBeVisible();
});

test("conflito resolvido sem alteração conclui com Registrar vazio", async ({
  page,
  manifesto,
  request,
}) => {
  const versao = manifesto.versoes[PapelVersao.CONFLITO];
  await abrir(page, manifesto.repo, versao);
  await atualizarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  const pendencias = (await (
    await request.get(rotaApi(manifesto.repo, RecursoApi.PENDENCIAS))
  ).json()) as { resultado: { worktree: string } }[];
  expect(pendencias).toHaveLength(1);
  // Fica com o lado do alvo: a resolução zera o diff do commit.
  git(
    manifesto,
    pendencias[0]!.resultado.worktree,
    "checkout",
    "--ours",
    manifesto.arquivo_conflito,
  );
  await continuarComoVazio(page);
  await expect(avisoVazioRegistrado(page)).toBeVisible();
  await fecharDialogo(page);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoVerde(page)).toBeVisible();
});

test("abortar o bloqueio devolve as ações e não mexe na branch", async ({
  page,
  manifesto,
}) => {
  const versao = manifesto.versoes[PapelVersao.CONFLITO];
  const antes = pontaDaBranch(manifesto, versao);
  await abrir(page, manifesto.repo, versao);
  await atualizarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  await abortarBloqueio(page);
  await expect(acao(page, Acao.ATUALIZAR)).toBeEnabled();
  await expect(acao(page, Acao.CONTINUAR)).toBeHidden();
  expect(pontaDaBranch(manifesto, versao)).toBe(antes);
});

test("recarregar a página mantém o bloqueio e suas ações", async ({
  page,
  manifesto,
}) => {
  const versao = manifesto.versoes[PapelVersao.CONFLITO];
  await abrir(page, manifesto.repo, versao);
  await atualizarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  await page.reload();
  await expect(avisoBloqueio(page)).toBeVisible();
  await expect(acao(page, Acao.CONTINUAR)).toBeEnabled();
  await expect(acao(page, Acao.ABORTAR)).toBeEnabled();
});
