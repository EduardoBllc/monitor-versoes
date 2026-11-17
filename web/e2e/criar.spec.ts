import { expect, git, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  abrir,
  abrirNovaVersao,
  criarEPublicar,
  criarVersaoSugerida,
  opcaoVersao,
  proporNumeroDaVersao,
  recusaDeVersaoExistente,
  sugestaoDeVersao,
} from "./tela";

test("a sugestão oferecida inclui a versão nova", async ({ page, manifesto }) => {
  await abrir(page, manifesto.repo, manifesto.versoes[PapelVersao.VERDE]);
  await abrirNovaVersao(page);
  await expect(sugestaoDeVersao(page, manifesto.versao_nova)).toBeVisible();
});

test("um número já existente é recusado com mensagem", async ({ page, manifesto }) => {
  const existente = manifesto.versoes[PapelVersao.VERDE];
  await abrir(page, manifesto.repo, existente);
  await proporNumeroDaVersao(page, existente);
  await expect(recusaDeVersaoExistente(page, existente)).toBeVisible();
  await expect(criarEPublicar(page)).toBeDisabled();
});

test("criar a versão nova conclui e ela aparece na lista de versões", async ({
  page,
  manifesto,
}) => {
  await abrir(page, manifesto.repo, manifesto.versoes[PapelVersao.VERDE]);
  await criarVersaoSugerida(page, manifesto.versao_nova);
  await expect(await opcaoVersao(page, manifesto.versao_nova)).toBeVisible();
  expect(git(manifesto, manifesto.clone, "branch", "--list", manifesto.versao_nova)).toContain(
    manifesto.versao_nova,
  );
});
