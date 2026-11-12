import { SimpleGrid, Stack, Text } from "@mantine/core";
import { Editor, type OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import { useEffect, useRef, useState } from "react";
import type { ConteudoDoConflito } from "../api/tipos";
import {
  type Bloco,
  CONTEXTO,
  type Decisao,
  EstadoBloco,
  type Faixa,
  Lado,
  aceitouLado,
  blocos,
  estadoDoBloco,
  localizar,
  recolher,
  secoesDoBloco,
  temMarcadores,
  trecho,
} from "../conflito";
import "./EditorConflito.css";
import {
  Classe,
  SO_LEITURA,
  colorir,
  decoracoes,
  recolherNoEditor,
} from "./monacoConflito";

const ALTURA_LADO = "35vh";
const ALTURA_RESULTADO = "45vh";
const COMANDO_ACEITAR = "monitor-versoes.aceitar";
// Lente sem id vira texto sem clique.
const SEM_ACAO = "";
// O bloco não cresce quando se digita na borda dele: a borda é a linha vizinha.
const RASTRO: monaco.editor.IModelDecorationOptions = {
  stickiness: monaco.editor.TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
};

type Lateral = Lado.OURS | Lado.THEIRS;

const ROTULO: Record<Lateral, string> = {
  [Lado.OURS]: "Aceitar ours",
  [Lado.THEIRS]: "Aceitar theirs",
};
const COR_DO_LADO: Record<Lateral, Classe> = {
  [Lado.OURS]: Classe.OURS,
  [Lado.THEIRS]: Classe.THEIRS,
};
const COR_DA_SECAO: Record<Lado.OURS | Lado.BASE | Lado.THEIRS, Classe> = {
  [Lado.OURS]: Classe.OURS,
  [Lado.BASE]: Classe.BASE,
  [Lado.THEIRS]: Classe.THEIRS,
};

// O índice no registro é a identidade do bloco nos três painéis.
type Registro = { original: Bloco; decisao: Decisao | null; id: string };
type Instantaneo = { faixas: monaco.IRange[]; decisoes: (Decisao | null)[] };

// A faixa de rastreio cobre o texto exato do bloco, com a quebra final.
function linhasDa(f: monaco.Range): Faixa {
  if (f.isEmpty())
    return { inicio: f.startLineNumber, fim: f.startLineNumber - 1 };
  const fim =
    f.endColumn === 1 && f.endLineNumber > f.startLineNumber
      ? f.endLineNumber - 1
      : f.endLineNumber;
  return { inicio: f.startLineNumber, fim };
}

// O texto como o Monaco o guarda: ele também quebra linha em \r solto e
// normaliza o EOL. Linha de `blocos` e linha do modelo precisam ser a mesma.
function comoMonaco(texto: string): string {
  const modelo = monaco.editor.createModel(texto);
  try {
    return modelo.getValue();
  } finally {
    modelo.dispose();
  }
}

export function MergeConteudo({
  linguagem,
  modelos,
  dados,
  texto,
  resolvido,
  tema,
  aoMudar,
}: {
  linguagem: string;
  modelos: Record<Lado.OURS | Lado.THEIRS | "resultado", string>;
  dados: ConteudoDoConflito;
  texto: string;
  resolvido: boolean;
  tema: string;
  aoMudar: (texto: string) => void;
}) {
  // Os blocos de quando a tela montou; a chave do componente troca a cada leitura.
  const [inicial] = useState(() => comoMonaco(texto));
  const [originais] = useState(() => (resolvido ? [] : blocos(inicial)));
  const [linhasIniciais] = useState(() => inicial.split("\n"));
  const registro = useRef<Registro[]>([]);
  const resultado = useRef<monaco.editor.ITextModel | null>(null);
  const [mudou] = useState(() => new monaco.Emitter<void>());
  const aceitar = useRef<(k: number, lado: Lado) => void>(() => {});

  useEffect(() => {
    const comando = monaco.editor.addCommand({
      id: COMANDO_ACEITAR,
      run: (_acesso: unknown, k: number, lado: Lado) =>
        aceitar.current(k, lado),
    });
    return () => comando.dispose();
  }, []);

  const estado = (k: number): EstadoBloco => {
    const r = registro.current[k];
    const modelo = resultado.current;
    const f = r && modelo?.getDecorationRange(r.id);
    // Resultado ainda montando: os lados já mostram o bloco como aberto.
    if (!r || !modelo || !f) return EstadoBloco.ABERTO;
    return estadoDoBloco(modelo.getValueInRange(f), r.decisao);
  };

  // Registros feitos no onMount morrem com o editor, não com o efeito do React:
  // no StrictMode o efeito roda duas vezes e o onMount uma só.
  const aoDescartar = (
    editor: monaco.editor.ICodeEditor,
    itens: monaco.IDisposable[],
  ) => editor.onDidDispose(() => itens.forEach((i) => i.dispose()));

  // Cada provider avisa com ele mesmo; o `mudou` é o sinal comum dos três painéis.
  const lentes = (
    modelo: monaco.editor.ITextModel,
    gerar: () => monaco.languages.CodeLens[],
  ): monaco.IDisposable => {
    const emissor = new monaco.Emitter<monaco.languages.CodeLensProvider>();
    const provider: monaco.languages.CodeLensProvider = {
      onDidChange: emissor.event,
      provideCodeLenses: (m) => ({
        lenses: m === modelo && !resolvido ? gerar() : [],
        dispose: () => {},
      }),
    };
    const itens = [
      mudou.event(() => emissor.fire(provider)),
      monaco.languages.registerCodeLensProvider("*", provider),
      emissor,
    ];
    return { dispose: () => itens.forEach((i) => i.dispose()) };
  };

  const montarLado =
    (lado: Lateral): OnMount =>
    (editor) => {
      const modelo = editor.getModel();
      if (!modelo) return;
      const faixas = localizar(
        modelo.getValue(),
        originais.map((b) => (lado === Lado.OURS ? b.ours : b.theirs)),
        originais.map((b) => {
          // Até CONTEXTO linhas antes do bloco, sem entrar no bloco anterior.
          const antes = linhasIniciais.slice(
            Math.max(0, b.inicio - 1 - CONTEXTO),
            b.inicio - 1,
          );
          let i = antes.length;
          while (i > 0 && !temMarcadores(antes[i - 1] ?? "")) i--;
          return antes.slice(i);
        }),
      );
      colorir(
        editor,
        faixas.map((faixa) => ({ faixa, classe: COR_DO_LADO[lado] })),
      );
      aoDescartar(editor, [
        recolherNoEditor(
          editor,
          recolher(modelo.getLineCount(), faixas, CONTEXTO),
        ),
        lentes(modelo, () =>
          faixas.flatMap((f, k) => {
            const e = estado(k);
            if (e === EstadoBloco.EDITADO) return [];
            const aceito =
              e === EstadoBloco.DECIDIDO &&
              aceitouLado(registro.current[k]?.decisao ?? null, lado);
            const linha = Math.min(f.inicio, modelo.getLineCount());
            return [
              {
                range: new monaco.Range(linha, 1, linha, 1),
                command: aceito
                  ? { id: SEM_ACAO, title: "✓ aceito" }
                  : {
                      id: COMANDO_ACEITAR,
                      title: ROTULO[lado],
                      arguments: [k, lado],
                    },
              },
            ];
          }),
        ),
      ]);
    };

  const montarResultado: OnMount = (editor) => {
    const modelo = editor.getModel();
    if (!modelo) return;
    resultado.current = modelo;
    const total = modelo.getLineCount();
    const faixaInicial = (b: Bloco) =>
      b.fim < total
        ? new monaco.Range(b.inicio, 1, b.fim + 1, 1)
        : new monaco.Range(b.inicio, 1, b.fim, modelo.getLineMaxColumn(b.fim));
    const ids = modelo.deltaDecorations(
      [],
      originais.map((b) => ({ range: faixaInicial(b), options: RASTRO })),
    );
    registro.current = originais.map((original, k) => ({
      original,
      decisao: null,
      id: ids[k] ?? "",
    }));

    // O Ctrl+Z volta o texto mas não as faixas de rastreio nem as decisões:
    // cada versão em que um Aceitar mexeu guarda as duas, e a volta a ela as restaura.
    const instantaneos = new Map<number, Instantaneo>();
    const fotografar = () =>
      instantaneos.set(modelo.getAlternativeVersionId(), {
        faixas: registro.current.map(
          (r) => modelo.getDecorationRange(r.id) ?? new monaco.Range(1, 1, 1, 1),
        ),
        decisoes: registro.current.map((r) => r.decisao),
      });
    const restaurar = () => {
      const foto = instantaneos.get(modelo.getAlternativeVersionId());
      if (!foto) return;
      const novos = modelo.deltaDecorations(
        registro.current.map((r) => r.id),
        foto.faixas.map((range) => ({ range, options: RASTRO })),
      );
      registro.current = registro.current.map((r, k) => ({
        ...r,
        id: novos[k] ?? r.id,
        decisao: foto.decisoes[k] ?? null,
      }));
    };

    const pintura = editor.createDecorationsCollection();
    const atualizar = () => {
      const linhas = registro.current.flatMap((r, k) => {
        const f = modelo.getDecorationRange(r.id);
        if (!f) return [];
        const faixa = linhasDa(f);
        switch (estado(k)) {
          case EstadoBloco.ABERTO:
            return [
              { faixa, classe: Classe.ABERTO },
              ...blocos(modelo.getValueInRange(f)).flatMap((b) =>
                secoesDoBloco(b).map((s) => ({
                  faixa: {
                    inicio: s.faixa.inicio + faixa.inicio - 1,
                    fim: s.faixa.fim + faixa.inicio - 1,
                  },
                  classe: s.lado === null ? Classe.MARCADOR : COR_DA_SECAO[s.lado],
                })),
              ),
            ];
          case EstadoBloco.DECIDIDO:
            return [{ faixa, classe: Classe.DECIDIDO }];
          case EstadoBloco.EDITADO:
            return [];
        }
      });
      pintura.set(decoracoes(linhas));
      mudou.fire();
    };

    aceitar.current = (k, lado) => {
      const r = registro.current[k];
      const f = r && modelo.getDecorationRange(r.id);
      if (!r || !f || estado(k) === EstadoBloco.EDITADO) return;
      // Bloco no fim sem quebra final: o trecho também termina sem ela.
      const semQuebra =
        f.endLineNumber === modelo.getLineCount() && f.endColumn > 1;
      const bruto = trecho(r.original, lado);
      const novo = semQuebra ? bruto.replace(/\r?\n$/, "") : bruto;
      // A lente não leva o foco, e sem ele o Ctrl+Z logo depois não chega aqui.
      // Focar antes de avisar as lentes: o blur do painel do lado cancela a
      // atualização pendente das lentes dele.
      editor.focus();
      fotografar();
      editor.pushUndoStop();
      editor.executeEdits(COMANDO_ACEITAR, [{ range: f, text: novo }]);
      editor.pushUndoStop();
      const partes = novo.split("\n");
      const fimLinha = f.startLineNumber + partes.length - 1;
      const fimColuna =
        partes.at(-1) === "" ? 1 : modelo.getLineMaxColumn(fimLinha);
      const faixa = new monaco.Range(f.startLineNumber, 1, fimLinha, fimColuna);
      const [id] = modelo.deltaDecorations(
        [r.id],
        [{ range: faixa, options: RASTRO }],
      );
      registro.current[k] = {
        ...r,
        id: id ?? r.id,
        decisao: { lado, texto: modelo.getValueInRange(faixa) },
      };
      fotografar();
      atualizar();
    };

    aoDescartar(editor, [
      modelo.onDidChangeContent(() => {
        restaurar();
        atualizar();
      }),
      recolherNoEditor(
        editor,
        recolher(
          total,
          originais.map((b) => ({ inicio: b.inicio, fim: b.fim })),
          CONTEXTO,
        ),
      ),
      lentes(modelo, () =>
        registro.current.flatMap((r, k) => {
          const f = modelo.getDecorationRange(r.id);
          if (!f || estado(k) !== EstadoBloco.ABERTO) return [];
          const acoes: [Lado, string][] = [[Lado.AMBOS, "Ambos"]];
          if (r.original.base !== null) acoes.push([Lado.BASE, "Usar base"]);
          return acoes.map(([lado, title]) => ({
            range: new monaco.Range(f.startLineNumber, 1, f.startLineNumber, 1),
            command: { id: COMANDO_ACEITAR, title, arguments: [k, lado] },
          }));
        }),
      ),
    ]);
    atualizar();
  };

  return (
    <Stack>
      <SimpleGrid cols={2}>
        <Text fw={700}>theirs — commit aplicado</Text>
        <Text fw={700}>ours — alvo</Text>
        <Editor
          height={ALTURA_LADO}
          language={linguagem}
          path={modelos[Lado.THEIRS]}
          value={dados.theirs ?? ""}
          theme={tema}
          options={SO_LEITURA}
          onMount={montarLado(Lado.THEIRS)}
        />
        <Editor
          height={ALTURA_LADO}
          language={linguagem}
          path={modelos[Lado.OURS]}
          value={dados.ours ?? ""}
          theme={tema}
          options={SO_LEITURA}
          onMount={montarLado(Lado.OURS)}
        />
      </SimpleGrid>
      <Text fw={700}>resultado</Text>
      <Editor
        height={ALTURA_RESULTADO}
        language={linguagem}
        path={modelos.resultado}
        value={texto}
        theme={tema}
        options={{ readOnly: resolvido, minimap: { enabled: false } }}
        onMount={montarResultado}
        onChange={(v) => aoMudar(v ?? "")}
      />
    </Stack>
  );
}
