import { expect, test } from "./fixtures";
import { PapelVersao, VERSAO_INEXISTENTE } from "./papeis";
import {
  Acao,
  abrir,
  acao,
  chamadoListado,
  erro,
  repoNaInicio,
  tituloDaVersao,
} from "./tela";

test("abre repo e versão por URL direta", async ({ page, manifesto }) => {
  const versao = manifesto.versoes[PapelVersao.VERDE];
  await abrir(page, manifesto.repo, versao);
  await expect(tituloDaVersao(page)).toHaveText(versao);
  await expect(
    chamadoListado(page, manifesto.chamados[PapelVersao.VERDE]),
  ).toBeVisible();
});

test("repo sem checkout fica indisponível", async ({ page, manifesto }) => {
  await abrir(page, manifesto.repo_sem_checkout);
  await expect(acao(page, Acao.NOVA_VERSAO)).toBeDisabled();
  await expect(await repoNaInicio(page, manifesto.repo_sem_checkout)).toBeDisabled();
});

test("versão inexistente mostra erro", async ({ page, manifesto }) => {
  // Lacuna da UI atual: a versão inexistente cai em "Nenhum snapshot ainda", sem erro.
  test.fail();
  await abrir(page, manifesto.repo, VERSAO_INEXISTENTE);
  await expect(erro(page)).toBeVisible();
});
