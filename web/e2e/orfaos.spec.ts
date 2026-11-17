import { RecursoApi, expect, rotaApi, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import { abrir, abrirOrfaos, julgarOrfao, linhaDoOrfao, orfaoJulgado } from "./tela";

const MOTIVO = "veio de outra frente";

interface Orfao {
  assunto: string;
  julgamento: { chamado: string | null; motivo: string } | null;
}

test("órfãos lista o commit sem referência e julgá-lo o marca como julgado", async ({
  page,
  manifesto,
  request,
}) => {
  const { repo, assunto_orfao: assunto } = manifesto;
  const versao = manifesto.versoes[PapelVersao.ORFAO];
  const chamado = manifesto.chamados[PapelVersao.VERDE];
  await abrir(page, repo, versao);
  await abrirOrfaos(page);
  await expect(linhaDoOrfao(page, repo, versao, assunto)).toBeVisible();

  await julgarOrfao(page, repo, versao, assunto, chamado, MOTIVO);

  await expect(orfaoJulgado(page, repo, versao, assunto, chamado, MOTIVO)).toBeVisible();
  const orfaos = (await (
    await request.get(rotaApi(repo, RecursoApi.ORFAOS, versao))
  ).json()) as Orfao[];
  expect(orfaos.find((o) => o.assunto === assunto)?.julgamento).toMatchObject({
    chamado,
    motivo: MOTIVO,
  });
});
