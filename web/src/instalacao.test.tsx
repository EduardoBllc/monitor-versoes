import { MantineProvider } from "@mantine/core";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { GrupoPlugin, TipoOrigem } from "./api/enums";
import type { Instalacao, Novidade, PluginInstalado } from "./api/tipos";
import { Barra, type PropsBarra } from "./componentes/Barra";
import { Secao } from "./configSecoes";
import { PACOTE_MOTOR, pluginsDaSecao } from "./instalacao";

const COMANDO_MOTOR = `${PACOTE_MOTOR} atualizar-motor`;
const NOVIDADE_MOTOR: Novidade = {
  pacote: PACOTE_MOTOR,
  atual: "0.2.0",
  nova: "0.3.0",
  comando: COMANDO_MOTOR,
};
const AVISO_MOTOR = "Versão 0.3.0 disponível (você tem 0.2.0):";

const plugin = (grupo: GrupoPlugin, pacote: string): PluginInstalado => ({
  grupo,
  nome: pacote,
  pacote,
  versao: "1.0.0",
  origem: { tipo: TipoOrigem.GIT, url: null, ref: null, commit: null },
});

const nada = () => undefined;
const PROPS: PropsBarra = {
  repos: [],
  versoes: [],
  ocupado: false,
  novidades: [],
  aoEscolherRepo: nada,
  aoEscolherVersao: nada,
  aoVerificar: nada,
  aoCriar: nada,
  aoInscricoes: nada,
  aoOrfaos: nada,
  aoConfigurar: nada,
};

const barra = (novidades: Novidade[]) =>
  renderToStaticMarkup(
    <MantineProvider>
      <Barra {...PROPS} novidades={novidades} />
    </MantineProvider>,
  );

describe("Barra", () => {
  it("mostra a versão nova com o comando a rodar", () => {
    const html = barra([NOVIDADE_MOTOR]);
    expect(html).toContain(AVISO_MOTOR);
    expect(html).toMatch(new RegExp(`<code[^>]*>${COMANDO_MOTOR}</code>`));
  });

  it("não mostra aviso sem versão nova", () => {
    expect(barra([])).not.toContain("disponível");
  });
});

describe("pluginsDaSecao", () => {
  const prs = plugin(GrupoPlugin.PRS, "plugin-prs");
  const tarefas = plugin(GrupoPlugin.TAREFAS, "plugin-tarefas");
  const instalacao: Instalacao = {
    plugins: [prs, tarefas],
    novidades: [{ ...NOVIDADE_MOTOR, pacote: prs.pacote, nova: "1.1.0" }],
  };

  it("a seção Fonte de PR lista os plugins do grupo prs com a versão nova", () => {
    expect(pluginsDaSecao(instalacao, Secao.PRS)).toEqual([
      { plugin: prs, nova: "1.1.0" },
    ]);
  });

  it("plugin em dia vem sem versão nova", () => {
    expect(pluginsDaSecao(instalacao, Secao.TAREFAS)).toEqual([
      { plugin: tarefas, nova: null },
    ]);
  });
});
