import { execFileSync } from "node:child_process";
import { expect, test, type Manifesto } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  abrir,
  acao,
  avisoBloqueio,
  avisoVazioRegistrado,
  chamadoNoLote,
  confirmarAbortar,
  confirmarLote,
  fecharDialogo,
  resultadoAtualizacao,
  vereditoVerde,
} from "./tela";

const TRAILER_CHERRY_PICK = "cherry picked from commit";

// Ambiente do cenário: o git não lê a config de quem roda.
function git(manifesto: Manifesto, cwd: string, ...args: string[]): string {
  return execFileSync("git", args, {
    cwd,
    env: { ...process.env, ...manifesto.ambiente },
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

const pontaDaBranch = (manifesto: Manifesto, versao: string): string =>
  git(manifesto, manifesto.clone, "rev-parse", versao);

test("atualizar aplica o lote com trailer e a versão fica verde", async ({
  page,
  manifesto,
}) => {
  const versao = manifesto.versoes[PapelVersao.FALTANTES];
  await abrir(page, manifesto.repo, versao);
  await acao(page, Acao.ATUALIZAR).click();
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
  // O motor registra sozinho o pick que sai vazio no lote: "Registrar vazio" só aparece
  // quando uma resolução de conflito zera o diff (teste seguinte).
  const versao = manifesto.versoes[PapelVersao.VAZIO];
  await abrir(page, manifesto.repo, versao);
  await acao(page, Acao.ATUALIZAR).click();
  await confirmarLote(page, versao);
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
  await acao(page, Acao.ATUALIZAR).click();
  await confirmarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  const [pendencia] = (await (
    await request.get(`/api/repos/${encodeURIComponent(manifesto.repo)}/pendencias`)
  ).json()) as { resultado: { worktree: string } }[];
  // Fica com o lado do alvo: a resolução zera o diff do commit.
  git(manifesto, pendencia!.resultado.worktree, "checkout", "--ours", manifesto.arquivo_conflito);
  await acao(page, Acao.CONTINUAR).click();
  await acao(page, Acao.REGISTRAR_VAZIO).click();
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
  await acao(page, Acao.ATUALIZAR).click();
  await confirmarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  await acao(page, Acao.ABORTAR).click();
  await confirmarAbortar(page);
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
  await acao(page, Acao.ATUALIZAR).click();
  await confirmarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  await page.reload();
  await expect(avisoBloqueio(page)).toBeVisible();
  await expect(acao(page, Acao.CONTINUAR)).toBeEnabled();
  await expect(acao(page, Acao.ABORTAR)).toBeEnabled();
});
