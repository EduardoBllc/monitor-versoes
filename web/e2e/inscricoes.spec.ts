import { expect, test, rodarInscricoes } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  abrir,
  acao,
  avisoDaRodada,
  inscreverSelecionada,
  inscricaoNuncaExecutou,
  linhaDaInscricao,
  removerInscricao,
} from "./tela";

// Cobre o intervalo de consulta da web (15 s) com folga.
const ESPERA_AVISO_MS = 30_000;

test("inscrever, rodar e remover", async ({ page, manifesto, raiz }) => {
  const versao = manifesto.versoes[PapelVersao.FALTANTES];
  await abrir(page, manifesto.repo, versao);
  await acao(page, Acao.INSCRICOES).click();
  await inscreverSelecionada(page);
  await expect(inscricaoNuncaExecutou(page, versao)).toBeVisible();

  rodarInscricoes(manifesto, raiz);

  await expect(avisoDaRodada(page, versao, manifesto.repo)).toBeVisible({
    timeout: ESPERA_AVISO_MS,
  });
  await expect(inscricaoNuncaExecutou(page, versao)).toBeHidden();

  await removerInscricao(page, versao);
  await expect(linhaDaInscricao(page, versao)).toHaveCount(0);
});
