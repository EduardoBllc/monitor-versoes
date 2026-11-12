import * as monaco from "monaco-editor";
import type { Faixa } from "../conflito";

export enum Classe {
  OURS = "cf-ours",
  THEIRS = "cf-theirs",
  BASE = "cf-base",
  MARCADOR = "cf-marcador",
  ABERTO = "cf-aberto",
  DECIDIDO = "cf-decidido",
}

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
