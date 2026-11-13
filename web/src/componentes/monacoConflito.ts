import * as monaco from "monaco-editor";
import type { PropostaDeBloco } from "../api/tipos";
import type { Faixa } from "../conflito";

export enum Classe {
  OURS = "cf-ours",
  THEIRS = "cf-theirs",
  BASE = "cf-base",
  MARCADOR = "cf-marcador",
  ABERTO = "cf-aberto",
  DECIDIDO = "cf-decidido",
}

export enum ClasseProposta {
  FAIXA = "cf-proposta",
  TITULO = "cf-proposta-titulo",
  CONTEUDO = "cf-proposta-conteudo",
  PORQUE = "cf-proposta-porque",
  ACOES = "cf-proposta-acoes",
  ICONE = "codicon codicon-sparkle",
}

export const SO_LEITURA = { readOnly: true, minimap: { enabled: false } };

// Classes da margem (barra de estado); as outras pintam a linha inteira.
const NA_MARGEM: readonly Classe[] = [Classe.ABERTO, Classe.DECIDIDO];
const ALTURA_AVISO = 1;
const NUNCA_CRESCE =
  monaco.editor.TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges;

type ComAreasOcultas = {
  setHiddenAreas(faixas: monaco.IRange[], dono?: unknown): void;
};

const intervalo = (f: Faixa): monaco.IRange =>
  new monaco.Range(f.inicio, 1, f.fim, 1);

// Esconde cada faixa e põe no lugar uma linha "⋯ N linhas" que a reabre no clique.
export function recolherNoEditor(
  editor: monaco.editor.ICodeEditor,
  ocultas: Faixa[],
): monaco.IDisposable {
  // ponytail: setHiddenAreas é interno do Monaco (o diff editor o usa para
  // recolher o que não mudou) e estável há anos; se sumir, a saída são dobras.
  const comAreas = editor as unknown as ComAreasOcultas;
  const dono = {};
  // O setHiddenAreas guarda as faixas cruas; quem as acompanha nas edições
  // (aceitar encolhe ou cresce um bloco) é este rastro de decorações.
  const opcoes = { stickiness: NUNCA_CRESCE };
  const rastro = editor.createDecorationsCollection(
    ocultas.map((f) => ({ range: intervalo(f), options: opcoes })),
  );
  let zonas: string[] = [];
  let avisos: monaco.editor.IOverlayWidget[] = [];
  let aplicadas = "";
  const aplicar = () => {
    const faixas = rastro.getRanges();
    const chave = faixas.map((r) => `${r.startLineNumber}-${r.endLineNumber}`).join();
    if (chave === aplicadas) return;
    aplicadas = chave;
    comAreas.setHiddenAreas(faixas, dono);
    avisos.forEach((a) => editor.removeOverlayWidget(a));
    editor.changeViewZones((acesso) => {
      zonas.forEach((z) => acesso.removeZone(z));
      const novos = faixas.map((r, i) => {
        // A view zone abre o espaço, mas fica sob a camada de texto e não
        // recebe clique; o aviso clicável é um overlay que segue a zona,
        // como o diff editor do Monaco faz nas regiões recolhidas.
        const aviso = document.createElement("div");
        const n = r.endLineNumber - r.startLineNumber + 1;
        aviso.className = "cf-recolhido";
        aviso.textContent = `⋯ ${n} ${n === 1 ? "linha" : "linhas"}`;
        aviso.onclick = () => {
          rastro.set(
            rastro
              .getRanges()
              .filter((_, j) => j !== i)
              .map((range) => ({ range, options: opcoes })),
          );
          aplicar();
        };
        const widget: monaco.editor.IOverlayWidget = {
          getId: () => `cf-recolhido-${i}-${r.startLineNumber}`,
          getDomNode: () => aviso,
          getPosition: () => null,
        };
        const zona = acesso.addZone({
          afterLineNumber: r.startLineNumber - 1,
          heightInLines: ALTURA_AVISO,
          // A zona fica junto da área escondida; sem isto o Monaco a some.
          showInHiddenAreas: true,
          domNode: document.createElement("div"),
          onDomNodeTop: (topo) => {
            aviso.style.top = `${topo}px`;
          },
          onComputedHeight: (altura) => {
            aviso.style.height = `${altura}px`;
          },
        });
        return { zona, widget };
      });
      zonas = novos.map((n) => n.zona);
      avisos = novos.map((n) => n.widget);
    });
    avisos.forEach((a) => editor.addOverlayWidget(a));
  };
  aplicar();
  const ouvinte = editor.onDidChangeModelContent(aplicar);
  return {
    dispose: () => {
      ouvinte.dispose();
      avisos.forEach((a) => editor.removeOverlayWidget(a));
      rastro.clear();
    },
  };
}

export function colorir(
  editor: monaco.editor.ICodeEditor,
  linhas: { faixa: Faixa; classe: Classe }[],
): monaco.editor.IEditorDecorationsCollection {
  return editor.createDecorationsCollection(decoracoes(linhas));
}

export const decoracoes = (
  linhas: { faixa: Faixa; classe: Classe }[],
): monaco.editor.IModelDeltaDecoration[] =>
  linhas
    .filter(({ faixa }) => faixa.fim >= faixa.inicio)
    .map(({ faixa, classe }) => ({
      range: intervalo(faixa),
      options: NA_MARGEM.includes(classe)
        ? { isWholeLine: true, linesDecorationsClassName: classe }
        : { isWholeLine: true, className: classe },
    }));

function elemento<T extends keyof HTMLElementTagNameMap>(
  tag: T,
  classe: string,
  texto = "",
): HTMLElementTagNameMap[T] {
  const no = document.createElement(tag);
  no.className = classe;
  no.textContent = texto;
  return no;
}

function botao(texto: string, aoClicar: () => void): HTMLButtonElement {
  const no = document.createElement("button");
  no.type = "button";
  no.textContent = texto;
  no.onclick = aoClicar;
  return no;
}

// Conteúdo e justificativa vêm do provedor: só textContent, nunca innerHTML.
export function noDaProposta(
  p: PropostaDeBloco,
  aoAplicar: () => void,
  aoDescartar: () => void,
): HTMLElement {
  const titulo = elemento("div", ClasseProposta.TITULO);
  titulo.append(
    elemento("span", ClasseProposta.ICONE),
    "Proposta para este bloco",
  );
  const acoes = elemento("div", ClasseProposta.ACOES);
  acoes.append(botao("Aplicar", aoAplicar), botao("Descartar", aoDescartar));
  const no = elemento("div", ClasseProposta.FAIXA);
  no.append(
    titulo,
    elemento("pre", ClasseProposta.CONTEUDO, p.conteudo),
    elemento("div", ClasseProposta.PORQUE, `Por quê: ${p.justificativa}`),
    acoes,
  );
  return no;
}

// Técnica do recolherNoEditor: a zona abre o espaço e o overlay recebe o clique.
export function faixasAbaixo(
  editor: monaco.editor.ICodeEditor,
  itens: { depoisDe: number; no: HTMLElement }[],
): monaco.IDisposable {
  const { contentLeft, contentWidth } = editor.getLayoutInfo();
  const widgets = itens.map(({ no }, i): monaco.editor.IOverlayWidget => {
    no.style.left = `${contentLeft}px`;
    no.style.width = `${contentWidth}px`;
    return {
      getId: () => `cf-proposta-${i}`,
      getDomNode: () => no,
      getPosition: () => null,
    };
  });
  widgets.forEach((w) => editor.addOverlayWidget(w));
  let zonas: string[] = [];
  editor.changeViewZones((acesso) => {
    zonas = itens.map(({ depoisDe, no }) =>
      acesso.addZone({
        afterLineNumber: depoisDe,
        // Medida depois do addOverlayWidget: fora do DOM a altura é zero.
        heightInPx: no.offsetHeight,
        domNode: document.createElement("div"),
        onDomNodeTop: (topo) => {
          no.style.top = `${topo}px`;
        },
      }),
    );
  });
  return {
    dispose: () => {
      widgets.forEach((w) => editor.removeOverlayWidget(w));
      editor.changeViewZones((acesso) =>
        zonas.forEach((z) => acesso.removeZone(z)),
      );
    },
  };
}
