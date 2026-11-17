import { mkdir, readFile } from "node:fs/promises";
import { ROTA_CONFIG, atrasarRota, esperarRender, expect, test } from "./fixtures";
import {
  abrir,
  avisoConfiguracaoSalva,
  editarPisoETestar,
  sairDaConfiguracao,
  pisoNaConfiguracao,
  resultadoDoTeste,
  salvarConfiguracao,
} from "./tela";

const PISO = "1.0.0";
const ATRASO_CONFIG_MS = 1_500;

test("editar, testar e salvar a configuração", async ({ page, manifesto }) => {
  // O teste da seção valida o config inteiro, e o repo sem checkout do cenário aponta para
  // uma pasta que não existe.
  await mkdir(manifesto.pasta_sem_checkout);
  await abrir(page, manifesto.repo);
  await editarPisoETestar(page, manifesto.repo, PISO);
  await expect(resultadoDoTeste(page, manifesto.repo)).toBeVisible();
  await salvarConfiguracao(page);
  await expect(avisoConfiguracaoSalva(page)).toBeVisible();

  expect(await readFile(manifesto.config, "utf-8")).toContain(PISO);

  await sairDaConfiguracao(page);
  await expect(await pisoNaConfiguracao(page, manifesto.repo)).toHaveValue(PISO);
});

test("reabrir com a config lenta não descarta a seção nem a edição", async ({ page, manifesto }) => {
  await abrir(page, manifesto.repo);
  await pisoNaConfiguracao(page, manifesto.repo);
  await sairDaConfiguracao(page);
  await atrasarRota(page, ROTA_CONFIG, ATRASO_CONFIG_MS);
  const recarga = page.waitForResponse((r) => new URL(r.url()).pathname === ROTA_CONFIG);

  const campo = await pisoNaConfiguracao(page, manifesto.repo);
  await campo.fill(PISO);
  await (await recarga).finished();
  await esperarRender(page);

  await expect(campo).toHaveValue(PISO);
});
