import { expect, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  abrir,
  acao,
  atualizacaoNaLinha,
  atualizarLote,
  fecharDialogo,
  resultadoAtualizacao,
  subirAoRepo,
  verificacaoNaLinha,
  vereditoVerde,
} from "./tela";

test("a página do repo mostra a última verificação e atualização", async ({
  page,
  manifesto,
}) => {
  const verde = manifesto.versoes[PapelVersao.VERDE];
  await abrir(page, manifesto.repo, verde);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoVerde(page)).toBeVisible();
  await fecharDialogo(page);
  await subirAoRepo(page, manifesto.repo);
  await expect(verificacaoNaLinha(page, verde)).toBeVisible();

  const faltantes = manifesto.versoes[PapelVersao.FALTANTES];
  await abrir(page, manifesto.repo, faltantes);
  await atualizarLote(page, faltantes);
  await expect(resultadoAtualizacao(page)).toBeVisible();
  await fecharDialogo(page);
  await subirAoRepo(page, manifesto.repo);
  await expect(atualizacaoNaLinha(page, faltantes)).toBeVisible();
});
