import type { Theme } from "./theme";
import { useTheme } from "./theme";

export interface ChartColors {
  grid: string;
  axis: string;
  accent: string;
  warn: string;
  reference: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
}

/**
 * Recharts takes literal colour strings, not CSS variables, so the token values are mirrored
 * here per theme. Keep in sync with the palettes in src/index.css.
 */
const CHART_COLORS: Record<Theme, ChartColors> = {
  light: {
    grid: "#e0dcd4",
    axis: "#7a746b",
    accent: "#3b6ea8",
    warn: "#b3803a",
    reference: "#3b3833",
    tooltipBg: "#fdfcfa",
    tooltipBorder: "#d4cec3",
    tooltipText: "#1e1c19",
  },
  dark: {
    grid: "#22262d",
    axis: "#8b929d",
    accent: "#5fd6a5",
    warn: "#e8b166",
    reference: "#c7ccd4",
    tooltipBg: "#151a20",
    tooltipBorder: "#262b33",
    tooltipText: "#e8eaed",
  },
};

export function useChartColors(): ChartColors {
  const { theme } = useTheme();
  return CHART_COLORS[theme];
}

/** Shared Recharts <Tooltip> styling so every chart reads as one system. */
export function tooltipStyles(c: ChartColors) {
  return {
    contentStyle: {
      background: c.tooltipBg,
      border: `1px solid ${c.tooltipBorder}`,
      borderRadius: 9,
      fontSize: 12,
      color: c.tooltipText,
      boxShadow: "none",
    },
    labelStyle: { color: c.axis, fontSize: 11 },
    itemStyle: { color: c.tooltipText },
    cursor: { fill: c.grid, fillOpacity: 0.35 },
  };
}
