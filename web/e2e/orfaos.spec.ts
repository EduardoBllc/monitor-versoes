import { expect, test } from "./fixtures";
import { PapelVersao } from "./papeis";
import { Acao, abrir, acao, julgarOrfao, linhaDoOrfao } from "./tela";

const ASSUNTO_ORFAO = "ajuste sem tarefa";
const MOTIVO = "veio de outra frente";
const JULGADO_COMO = (chamado: string) => `pertence a ${chamado}`;

interface Orfao {
  assunto: string;
  julgamento: { chamado: string | null; motivo: string } | null;
}

test("órfãos lista o commit sem referência e julgá-lo o marca como julgado", async ({
  page,
  manifesto,
  request,
}) => {
  const versao = manifesto.versoes[PapelVersao.ORFAO];
  const chamado = manifesto.chamados[PapelVersao.VERDE];
  const url = `/api/repos/${encodeURIComponent(manifesto.repo)}/versoes/${encodeURIComponent(versao)}/orfaos`;
  await abrir(page, manifesto.repo, versao);
  await acao(page, Acao.ORFAOS).click();
  const linha = linhaDoOrfao(page, manifesto.repo, versao, ASSUNTO_ORFAO);
  await expect(linha).toBeVisible();

  await julgarOrfao(page, manifesto.repo, versao, ASSUNTO_ORFAO, chamado, MOTIVO);

  // A tela não remove o julgado: mantém a linha com o rótulo e o motivo.
  await expect(linha).toContainText(JULGADO_COMO(chamado));
  await expect(linha).toContainText(MOTIVO);
  const orfaos = (await (await request.get(url)).json()) as Orfao[];
  expect(orfaos.find((o) => o.assunto === ASSUNTO_ORFAO)?.julgamento).toMatchObject({
    chamado,
    motivo: MOTIVO,
  });
});
