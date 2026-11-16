import { expect, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  abrir,
  acao,
  avisoAuditoria,
  chamadoListado,
  vereditoPendencias,
  vereditoVerde,
} from "./tela";

test("verificar mostra o veredito de pendências do motor", async ({ page, manifesto }) => {
  // O indicador de progresso é transitório demais para asserção estável: só o veredito.
  await abrir(page, manifesto.repo, manifesto.versoes[PapelVersao.FALTANTES]);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoPendencias(page)).toBeVisible();
  await expect(
    chamadoListado(page, manifesto.chamados[PapelVersao.FALTANTES]),
  ).toBeVisible();
});

test("verificar uma versão verde mostra o veredito verde", async ({ page, manifesto }) => {
  await abrir(page, manifesto.repo, manifesto.versoes[PapelVersao.VERDE]);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoVerde(page)).toBeVisible();
});

test("auditar tag mantém o snapshot congelado", async ({ page, manifesto, request }) => {
  const versao = manifesto.versoes[PapelVersao.LIBERADA];
  const url = `/api/repos/${encodeURIComponent(manifesto.repo)}/versoes/${encodeURIComponent(versao)}/chamados`;
  const antes = await (await request.get(url)).json();
  await abrir(page, manifesto.repo, versao);
  await acao(page, Acao.AUDITAR).click();
  await expect(avisoAuditoria(page)).toBeVisible();
  expect(await (await request.get(url)).json()).toEqual(antes);
});
