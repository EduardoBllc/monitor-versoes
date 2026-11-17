import { expect, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import { abrirInicio, saltarPelaPaleta, tituloDaVersao } from "./tela";

test("ctrl+K salta para a versão de um chamado", async ({ page, manifesto }) => {
  const papel = PapelVersao.FALTANTES;
  await abrirInicio(page);
  await saltarPelaPaleta(page, manifesto.chamados[papel]);
  await expect(tituloDaVersao(page)).toContainText(manifesto.versoes[papel]);
});
