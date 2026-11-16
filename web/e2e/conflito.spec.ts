import { expect, git, test, type Manifesto } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  LadoConflito,
  aceitarLado,
  abrir,
  abrirArquivoDoConflito,
  acao,
  avisoBloqueio,
  confirmarLote,
  fecharDialogo,
  resultadoAtualizacao,
  vereditoVerde,
} from "./tela";

const MARCADOR_CONFLITO = "<<<<<<<";

const arquivoNaBranch = (manifesto: Manifesto, versao: string): string =>
  git(manifesto, manifesto.clone, "show", `${versao}:${manifesto.arquivo_conflito}`);

test("conflito resolvido no editor web continua sozinho e a versão fica verde", async ({
  page,
  manifesto,
}) => {
  const versao = manifesto.versoes[PapelVersao.CONFLITO];
  await abrir(page, manifesto.repo, versao);
  await acao(page, Acao.ATUALIZAR).click();
  await confirmarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  await acao(page, Acao.RESOLVER_NA_WEB).click();
  await abrirArquivoDoConflito(page, manifesto.arquivo_conflito);
  await aceitarLado(page, LadoConflito.THEIRS);
  await acao(page, Acao.MARCAR_RESOLVIDO).click();
  // Último arquivo resolvido: a web dispara o Continuar sozinha.
  await expect(resultadoAtualizacao(page)).toBeVisible();
  await fecharDialogo(page);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoVerde(page)).toBeVisible();
  expect(arquivoNaBranch(manifesto, versao)).not.toContain(MARCADOR_CONFLITO);
});
