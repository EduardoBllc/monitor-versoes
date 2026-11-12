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
  let restantes = ocultas;
  let zonas: string[] = [];
  let avisos: monaco.editor.IOverlayWidget[] = [];
  const aplicar = () => {
    comAreas.setHiddenAreas(restantes.map(intervalo), dono);
    avisos.forEach((a) => editor.removeOverlayWidget(a));
    editor.changeViewZones((acesso) => {
      zonas.forEach((z) => acesso.removeZone(z));
      const novos = restantes.map((f, i) => {
        // A view zone abre o espaço, mas fica sob a camada de texto e não
        // recebe clique; o aviso clicável é um overlay que segue a zona,
        // como o diff editor do Monaco faz nas regiões recolhidas.
        const aviso = document.createElement("div");
        const n = f.fim - f.inicio + 1;
        aviso.className = "cf-recolhido";
        aviso.textContent = `⋯ ${n} ${n === 1 ? "linha" : "linhas"}`;
        aviso.onclick = () => {
          restantes = restantes.filter((r) => r !== f);
          aplicar();
        };
        const widget: monaco.editor.IOverlayWidget = {
          getId: () => `cf-recolhido-${i}-${f.inicio}`,
          getDomNode: () => aviso,
          getPosition: () => null,
        };
        const zona = acesso.addZone({
          afterLineNumber: f.inicio - 1,
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
  return {
    dispose: () => {
      restantes = [];
      aplicar();
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
