import { mkdir, readFile } from "node:fs/promises";
import { expect, test } from "./fixtures";
import {
  abrir,
  avisoConfiguracaoSalva,
  editarPisoETestar,
  fecharDialogo,
  pisoNaConfiguracao,
  resultadoDoTeste,
  salvarConfiguracao,
} from "./tela";

const PISO = "1.0.0";

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

  await fecharDialogo(page);
  await expect(await pisoNaConfiguracao(page, manifesto.repo)).toHaveValue(PISO);
});
