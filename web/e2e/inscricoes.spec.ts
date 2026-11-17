import { expect, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  abrir,
  avisoDaRodada,
  esperarAvisoDaRodada,
  inscrever,
  inscricaoNuncaExecutou,
  linhaDaInscricao,
  removerInscricao,
} from "./tela";

test("inscrever, o daemon dispara a rodada e remover", async ({ page, manifesto }) => {
  const versao = manifesto.versoes[PapelVersao.FALTANTES];
  await abrir(page, manifesto.repo, versao);
  await inscrever(page);
  await expect(inscricaoNuncaExecutou(page, versao)).toBeVisible();

  await esperarAvisoDaRodada(page, versao, manifesto.repo);
  await expect(avisoDaRodada(page, versao, manifesto.repo)).toBeVisible();
  await expect(inscricaoNuncaExecutou(page, versao)).toBeHidden();

  await removerInscricao(page, versao);
  await expect(linhaDaInscricao(page, versao)).toHaveCount(0);
});
