import { expect, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import {
  abrir,
  abrirInicio,
  atualizarLote,
  avisoBloqueio,
  bloqueioNaInicio,
  repoIndisponivelNaInicio,
  resolverPelaInicio,
  tituloDaVersao,
  versaoNaInicio,
  voltarAoInicio,
} from "./tela";

test("a home lista as versões em aberto do repo", async ({ page, manifesto }) => {
  await abrirInicio(page);
  const versao = (papel: PapelVersao) =>
    versaoNaInicio(page, manifesto.repo, manifesto.versoes[papel]);
  // As abertas antes: com a lista já na tela, a ausência da liberada vale.
  for (const papel of Object.values(PapelVersao).filter((p) => p !== PapelVersao.LIBERADA))
    await expect(versao(papel)).toBeVisible();
  await expect(versao(PapelVersao.LIBERADA)).toHaveCount(0);
});

test("repo sem checkout aparece indisponível na home", async ({ page, manifesto }) => {
  await abrirInicio(page);
  await expect(repoIndisponivelNaInicio(page, manifesto.repo_sem_checkout)).toBeVisible();
});

test("atualização bloqueada aparece em precisa de você e leva à versão", async ({
  page,
  manifesto,
}) => {
  const versao = manifesto.versoes[PapelVersao.CONFLITO];
  await abrir(page, manifesto.repo, versao);
  await atualizarLote(page, versao);
  await expect(avisoBloqueio(page)).toBeVisible();
  await voltarAoInicio(page);
  await expect(bloqueioNaInicio(page, versao)).toBeVisible();
  await resolverPelaInicio(page, versao);
  await expect(tituloDaVersao(page)).toHaveText(versao);
});
