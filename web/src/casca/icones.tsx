import type { JSX, ReactNode } from "react";

const TAMANHO = 16;

// Sem biblioteca de ícones: os dois do cabeçalho no celular cabem aqui.
function Icone({ children }: { children: ReactNode }): JSX.Element {
  return (
    <svg
      width={TAMANHO}
      height={TAMANHO}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

export const IconeBusca = (): JSX.Element => (
  <Icone>
    <circle cx="10" cy="10" r="7" />
    <path d="M21 21l-6-6" />
  </Icone>
);

export const IconeConfig = (): JSX.Element => (
  <Icone>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1l2.1-2.1M17 7l2.1-2.1" />
  </Icone>
);
