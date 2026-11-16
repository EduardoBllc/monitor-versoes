import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { expect, test } from "./fixtures";
import {
  Acao,
  CampoRepo,
  abrir,
  abrirSecaoDaConfiguracao,
  acao,
  avisoConfiguracaoSalva,
  campoDaConfiguracao,
  fecharDialogo,
  resultadoDoTeste,
  salvarConfiguracao,
  testarSecao,
} from "./tela";

const PISO = "1.0.0";
const PASTA_SEM_CHECKOUT = "sem-checkout";
const CONFIG_RELATIVA = join("monitor-versoes", "config.toml");
const XDG_CONFIG_HOME = "XDG_CONFIG_HOME";

test("editar, testar e salvar a configuração", async ({ page, manifesto, raiz }) => {
  // O teste da seção valida o config inteiro, e o repo sem checkout do cenário aponta para
  // uma pasta que não existe.
  await mkdir(join(raiz, PASTA_SEM_CHECKOUT));
  await abrir(page, manifesto.repo);
  await acao(page, Acao.CONFIGURACAO).click();
  await abrirSecaoDaConfiguracao(page, manifesto.repo);
  await campoDaConfiguracao(page, CampoRepo.PISO).fill(PISO);
  await testarSecao(page);
  await expect(resultadoDoTeste(page, manifesto.repo)).toBeVisible();
  await salvarConfiguracao(page);
  await expect(avisoConfiguracaoSalva(page)).toBeVisible();

  const arquivo = join(manifesto.ambiente[XDG_CONFIG_HOME] ?? "", CONFIG_RELATIVA);
  expect(await readFile(arquivo, "utf-8")).toContain(PISO);

  await fecharDialogo(page);
  await acao(page, Acao.CONFIGURACAO).click();
  await abrirSecaoDaConfiguracao(page, manifesto.repo);
  await expect(campoDaConfiguracao(page, CampoRepo.PISO)).toHaveValue(PISO);
});
