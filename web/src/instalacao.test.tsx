import { MantineProvider } from "@mantine/core";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { GrupoPlugin, TipoOrigem } from "./api/enums";
import type { Instalacao, NovidadeVista, PluginInstalado } from "./api/tipos";
import { Barra, type PropsBarra } from "./componentes/Barra";
import { Secao } from "./configSecoes";
import { pluginsDaSecao } from "./instalacao";

const novidade = (pacote: string, comando: string, texto: string): NovidadeVista => ({
  pacote,
  atual: "0.2.0",
  nova: "0.3.0",
  comando,
  texto,
});
const NOVIDADE_MOTOR = novidade(
  "monitor-versoes",
  "monitor-versoes atualizar-motor",
  "Versão 0.3.0 disponível (você tem 0.2.0):",
);
const NOVIDADE_A = novidade(
  "plugin-a",
  "monitor-versoes plugin atualizar plugin-a",
  "plugin-a: Versão 0.3.0 disponível (você tem 0.2.0):",
);
const NOVIDADE_B = novidade(
  "plugin-b",
  "monitor-versoes plugin atualizar plugin-b",
  "plugin-b: Versão 0.3.0 disponível (você tem 0.2.0):",
);

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

const barra = (novidades: NovidadeVista[]) =>
  renderToStaticMarkup(
    <MantineProvider>
      <Barra {...PROPS} novidades={novidades} />
    </MantineProvider>,
  );

describe("Barra", () => {
  it("mostra a versão nova com o comando a rodar", () => {
    const html = barra([NOVIDADE_MOTOR]);
    expect(html).toContain(NOVIDADE_MOTOR.texto);
    expect(html).toMatch(new RegExp(`<code[^>]*>${NOVIDADE_MOTOR.comando}</code>`));
  });

  it("com várias, mostra a primeira e o resto num +N com title", () => {
    const html = barra([NOVIDADE_MOTOR, NOVIDADE_A, NOVIDADE_B]);
    expect(html).toContain(NOVIDADE_MOTOR.texto);
    const titulo = html.match(/title="([^"]*)"[^>]*> \+2</)?.[1];
    expect(titulo).toContain(`${NOVIDADE_A.texto} ${NOVIDADE_A.comando}`);
    expect(titulo).toContain(`${NOVIDADE_B.texto} ${NOVIDADE_B.comando}`);
    expect(html.match(/<code/g)).toHaveLength(1);
  });

  it("não mostra aviso sem versão nova", () => {
    expect(barra([])).not.toContain(NOVIDADE_MOTOR.texto);
  });
});

describe("pluginsDaSecao", () => {
  const prs = plugin(GrupoPlugin.PRS, "plugin-prs");
  const tarefas = plugin(GrupoPlugin.TAREFAS, "plugin-tarefas");
  const instalacao: Instalacao = {
    plugins: [prs, tarefas],
    novidades: [{ ...NOVIDADE_A, pacote: prs.pacote, nova: "1.1.0" }],
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

  it("plugin embutido não repete a versão nova do motor", () => {
    const embutido: PluginInstalado = {
      ...plugin(GrupoPlugin.PRS, NOVIDADE_MOTOR.pacote),
      origem: { tipo: TipoOrigem.EMBUTIDO, url: null, ref: null, commit: null },
    };
    const comMotor: Instalacao = { plugins: [embutido], novidades: [NOVIDADE_MOTOR] };
    expect(pluginsDaSecao(comMotor, Secao.PRS)).toEqual([
      { plugin: embutido, nova: null },
    ]);
  });
});
