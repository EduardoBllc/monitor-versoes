import { expect, segurarTrava, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import { Acao, abrir, acao, avisoRepoOcupado, vereditoVerde } from "./tela";

test("operação concorrente é recusada e a tela segue usável", async ({
  page,
  manifesto,
  raiz,
}) => {
  await abrir(page, manifesto.repo, manifesto.versoes[PapelVersao.VERDE]);
  const trava = await segurarTrava(manifesto, raiz);
  try {
    await acao(page, Acao.VERIFICAR).click();
    await expect(avisoRepoOcupado(page)).toBeVisible();
    await expect(vereditoVerde(page)).toBeHidden();
  } finally {
    await trava.soltar();
  }
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoVerde(page)).toBeVisible();
});
