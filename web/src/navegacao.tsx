import { Anchor, type AnchorProps } from "@mantine/core";
import {
  useEffect,
  useMemo,
  useSyncExternalStore,
  type JSX,
  type MouseEvent,
  type ReactNode,
} from "react";
import { AVISO_DESCARTE } from "./conflito";
import { caminhoDa, lerRota, type Rota } from "./rotas";

const BOTAO_PRINCIPAL = 0;

// Estado de módulo: há um só histórico por janela, e o provider das operações (acima
// de qualquer componente) também navega.
let atual = window.location.pathname;
let guardas = 0;
const ouvintes = new Set<() => void>();

const avisar = () => {
  for (const o of ouvintes) o();
};
const podeSair = () => guardas === 0 || window.confirm(AVISO_DESCARTE);

function aoVoltar() {
  if (window.location.pathname === atual) return;
  // O navegador já trocou a URL: recusar é devolvê-la.
  if (!podeSair()) {
    window.history.pushState(null, "", atual);
    return;
  }
  atual = window.location.pathname;
  avisar();
}

function assinar(ouvinte: () => void): () => void {
  if (ouvintes.size === 0) window.addEventListener("popstate", aoVoltar);
  ouvintes.add(ouvinte);
  return () => {
    ouvintes.delete(ouvinte);
    if (ouvintes.size === 0) window.removeEventListener("popstate", aoVoltar);
  };
}

export function ir(rota: Rota, trocar = false): void {
  const destino = caminhoDa(rota);
  if (destino === atual || !podeSair()) return;
  if (trocar) window.history.replaceState(null, "", destino);
  else window.history.pushState(null, "", destino);
  atual = destino;
  avisar();
}

export function useRota(): Rota {
  const caminho = useSyncExternalStore(assinar, () => atual);
  return useMemo(() => lerRota(caminho), [caminho]);
}

export function useIr(): (rota: Rota, trocar?: boolean) => void {
  return ir;
}

/** Clique num link da SPA: navega aqui, salvo quando o navegador deve abrir em outra aba. */
export function irNoClique(e: MouseEvent, para: Rota): void {
  // Ctrl/⌘/shift/botão do meio: deixa o navegador abrir em outra aba.
  if (
    e.button !== BOTAO_PRINCIPAL ||
    e.metaKey ||
    e.ctrlKey ||
    e.shiftKey ||
    e.altKey
  )
    return;
  e.preventDefault();
  ir(para);
}

export function Link({
  para,
  children,
  ...props
}: { para: Rota; children: ReactNode } & AnchorProps): JSX.Element {
  return (
    <Anchor href={caminhoDa(para)} onClick={(e) => irNoClique(e, para)} {...props}>
      {children}
    </Anchor>
  );
}

export function useGuardaDeSaida(sujo: boolean): void {
  useEffect(() => {
    if (!sujo) return;
    guardas += 1;
    return () => {
      guardas -= 1;
    };
  }, [sujo]);
}
