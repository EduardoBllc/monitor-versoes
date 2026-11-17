import {
  Button,
  Paper,
  createTheme,
  type MantineColorsTuple,
  type MantineThemeOverride,
} from "@mantine/core";

// Escala do mockup B (texto claro em [0], fundo em [7]), na ordem que o Mantine espera.
const escuro: MantineColorsTuple = [
  "#d6dbe1",
  "#b1bac4",
  "#8b949e",
  "#6e7681",
  "#30363d",
  "#1f252d",
  "#161b22",
  "#0d1014",
  "#0a0c10",
  "#06080a",
];

export const FONTE_MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
export const TAMANHO_HASH = 8;

export const tema: MantineThemeOverride = createTheme({
  colors: { dark: escuro },
  primaryColor: "green",
  fontFamilyMonospace: FONTE_MONO,
  defaultRadius: "sm",
  fontSizes: { xs: "11px", sm: "12.5px", md: "13.5px", lg: "15px", xl: "18px" },
  spacing: { xs: "6px", sm: "8px", md: "12px", lg: "16px", xl: "24px" },
  components: {
    Button: Button.extend({ defaultProps: { size: "compact-sm" } }),
    Paper: Paper.extend({ defaultProps: { withBorder: true } }),
  },
});
