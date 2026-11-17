import { expect, git, test, type Manifesto } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  Acao,
  LadoConflito,
  abrir,
  acao,
  atualizarLote,
  avisoBloqueio,
  editorDeConflito,
  fecharDialogo,
  navegarComEdicaoPendente,
  resolverBlocoNaWeb,
  resolverConflitoNaWeb,
  resultadoAtualizacao,
  tituloDaVersao,
  vereditoVerde,
} from "./tela";

const arquivoNaBranch = (manifesto: Manifesto, versao: string): string =>
  git(manifesto, manifesto.clone, "show", `${versao}:${manifesto.arquivo_conflito}`);

test("conflito resolvido no editor web continua sozinho e a versão fica verde", async ({
  page,
  manifesto,
}) => {
  const versao = manifesto.versoes[PapelVersao.CONFLITO];
  await abrir(page, manifesto.repo, versao);
  await atualizarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  await resolverConflitoNaWeb(page, manifesto.arquivo_conflito, LadoConflito.THEIRS);
  // Último arquivo resolvido: a web dispara o Continuar sozinha.
  await expect(resultadoAtualizacao(page)).toBeVisible();
  await fecharDialogo(page);
  await acao(page, Acao.VERIFICAR).click();
  await expect(vereditoVerde(page)).toBeVisible();
  // O `git` do fixture apara o fim de linha.
  expect(arquivoNaBranch(manifesto, versao)).toBe(
    manifesto.conteudo_theirs_conflito.trimEnd(),
  );
});

test("sair do editor com edição pendente pede confirmação", async ({ page, manifesto }) => {
  const versao = manifesto.versoes[PapelVersao.CONFLITO];
  await abrir(page, manifesto.repo, versao);
  await atualizarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  await resolverBlocoNaWeb(page, manifesto.arquivo_conflito, LadoConflito.THEIRS);

  await navegarComEdicaoPendente(page, false);
  await expect(editorDeConflito(page)).toBeVisible();

  await navegarComEdicaoPendente(page, true);
  await expect(tituloDaVersao(page)).toBeHidden();
});
