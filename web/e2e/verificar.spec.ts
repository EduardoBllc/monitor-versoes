import { RecursoApi, expect, rotaApi, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  abrir,
  acao,
  avisoAuditoria,
  avisoSemCommits,
  vereditoPendencias,
  vereditoVerde,
} from "./tela";

test("verificar mostra o veredito de pendências do motor", async ({ page, manifesto }) => {
  // O indicador de progresso é transitório demais para asserção estável: só o veredito.
  await abrir(page, manifesto.repo, manifesto.versoes[PapelVersao.FALTANTES]);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoPendencias(page)).toBeVisible();
});

test("verificar uma versão verde mostra o veredito verde", async ({ page, manifesto }) => {
  await abrir(page, manifesto.repo, manifesto.versoes[PapelVersao.VERDE]);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoVerde(page)).toBeVisible();
});

const CHAMADO_NOVO_NO_MAPA = "999";

test("auditar tag mantém o snapshot congelado", async ({
  page,
  manifesto,
  request,
  adicionarChamado,
}) => {
  const versao = manifesto.versoes[PapelVersao.LIBERADA];
  const url = rotaApi(manifesto.repo, RecursoApi.CHAMADOS, versao);
  const antes = await (await request.get(url)).json();
  await adicionarChamado(versao, CHAMADO_NOVO_NO_MAPA);
  await abrir(page, manifesto.repo, versao);
  await acao(page, Acao.AUDITAR).click();
  await expect(avisoAuditoria(page)).toBeVisible();
  await expect(avisoSemCommits(page, CHAMADO_NOVO_NO_MAPA)).toBeVisible();
  expect(await (await request.get(url)).json()).toEqual(antes);
});
