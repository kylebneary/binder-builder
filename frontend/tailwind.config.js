/**
 * Semantic colour names only -- every value resolves to a CSS custom property defined per
 * theme in src/index.css, so `data-theme` on <html> switches the whole app with no
 * `dark:` variants scattered through the components.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        raised: "var(--raised)",
        inset: "var(--inset)",
        well: "var(--well)",
        line: {
          DEFAULT: "var(--line)",
          strong: "var(--line-strong)",
          card: "var(--line-card)",
        },
        ink: {
          DEFAULT: "var(--text)",
          2: "var(--text-2)",
          3: "var(--text-3)",
          4: "var(--text-4)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          fg: "var(--accent-fg)",
          text: "var(--accent-text)",
          surface: "var(--accent-surface)",
          line: "var(--accent-line)",
          deep: "var(--accent-deep)",
        },
        warn: {
          DEFAULT: "var(--warn)",
          text: "var(--warn-text)",
          fg: "var(--warn-fg)",
          surface: "var(--warn-surface)",
          line: "var(--warn-line)",
        },
        danger: {
          DEFAULT: "var(--danger)",
          text: "var(--danger-text)",
          surface: "var(--danger-surface)",
          line: "var(--danger-line)",
        },
        track: {
          DEFAULT: "var(--track)",
          muted: "var(--track-muted)",
        },
        "nav-active": "var(--nav-active)",
        seg: "var(--seg-active)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      boxShadow: {
        card: "var(--shadow-card)",
        panel: "var(--shadow-panel)",
        lift: "var(--shadow-lift)",
        hero: "var(--shadow-hero)",
        glow: "var(--glow)",
        seg: "var(--seg-active-shadow)",
      },
      backgroundImage: {
        glow: "var(--canvas-glow)",
        // Flat tint in light, a soft vertical gradient in dark -- see --accent-panel.
        "accent-panel": "var(--accent-panel)",
      },
      aspectRatio: {
        card: "63 / 88",
        pocket: "5 / 7",
      },
    },
  },
  plugins: [],
};
