import { expect, git, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  abrir,
  acao,
  criarEPublicar,
  digitarNumeroDaVersao,
  opcaoVersao,
  recusaDeVersaoExistente,
  sugestaoDeVersao,
} from "./tela";

test("a sugestão oferecida inclui a versão nova", async ({ page, manifesto }) => {
  await abrir(page, manifesto.repo, manifesto.versoes[PapelVersao.VERDE]);
  await acao(page, Acao.NOVA_VERSAO).click();
  await expect(sugestaoDeVersao(page, manifesto.versao_nova)).toBeVisible();
});

test("um número já existente é recusado com mensagem", async ({ page, manifesto }) => {
  const existente = manifesto.versoes[PapelVersao.VERDE];
  await abrir(page, manifesto.repo, existente);
  await acao(page, Acao.NOVA_VERSAO).click();
  await digitarNumeroDaVersao(page, existente);
  await expect(recusaDeVersaoExistente(page, existente)).toBeVisible();
  await expect(criarEPublicar(page)).toBeDisabled();
});

test("criar a versão nova conclui e ela aparece na lista de versões", async ({
  page,
  manifesto,
}) => {
  await abrir(page, manifesto.repo, manifesto.versoes[PapelVersao.VERDE]);
  await acao(page, Acao.NOVA_VERSAO).click();
  await sugestaoDeVersao(page, manifesto.versao_nova).click();
  await expect(criarEPublicar(page)).toBeEnabled();
  await criarEPublicar(page).click();
  await expect(await opcaoVersao(page, manifesto.versao_nova)).toBeVisible();
  expect(git(manifesto, manifesto.clone, "branch", "--list", manifesto.versao_nova)).toContain(
    manifesto.versao_nova,
  );
});
