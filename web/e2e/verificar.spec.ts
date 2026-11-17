import { RecursoApi, expect, rotaApi, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  MotivoCommit,
  abrir,
  acao,
  avisoAuditoria,
  avisoSemCommits,
  commitDoChamado,
  expandirChamado,
  fecharDialogo,
  Veredito,
  vereditoDaPagina,
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

test("os commits de um chamado faltante aparecem com o motivo", async ({
  page,
  manifesto,
  request,
}) => {
  const versao = manifesto.versoes[PapelVersao.FALTANTES];
  const chamado = manifesto.chamados[PapelVersao.FALTANTES];
  await abrir(page, manifesto.repo, versao);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoPendencias(page)).toBeVisible();
  await fecharDialogo(page);
  await expect(vereditoDaPagina(page, Veredito.PENDENCIAS)).toBeVisible();
  const chamados = (await (
    await request.get(rotaApi(manifesto.repo, RecursoApi.CHAMADOS, versao))
  ).json()) as { chamado: string; commits: { hash_origem: string }[] }[];
  const hash = chamados.find((c) => c.chamado === chamado)!.commits[0]!.hash_origem;
  await expandirChamado(page, chamado);
  await expect(commitDoChamado(page, hash, MotivoCommit.FALTA)).toBeVisible();
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
