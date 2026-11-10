import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

const raiz = document.getElementById("root");
if (raiz === null) throw new Error("#root ausente no index.html");
createRoot(raiz).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
