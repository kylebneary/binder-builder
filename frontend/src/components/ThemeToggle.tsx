import { useTheme } from "../lib/theme";

/**
 * Light/dark switch, styled as the same segmented control the mockups use for 3x3 / 3x4 / 2x2.
 * The two themes are distinct designs (different accent hue and display typeface), not a
 * colour inversion, so this is a deliberate choice rather than a cosmetic preference.
 */
export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div
      role="group"
      aria-label="Colour theme"
      className="inline-flex gap-[3px] rounded-lg border border-line bg-inset p-[3px]"
    >
      <ThemeButton
        active={theme === "light"}
        label="Light"
        onClick={() => setTheme("light")}
        icon={<SunIcon />}
      />
      <ThemeButton
        active={theme === "dark"}
        label="Dark"
        onClick={() => setTheme("dark")}
        icon={<MoonIcon />}
      />
    </div>
  );
}

function ThemeButton({
  active,
  label,
  icon,
  onClick,
}: {
  active: boolean;
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={`${label} theme`}
      className={`flex h-[26px] w-[30px] items-center justify-center rounded-[5px] transition-colors ${
        active ? "bg-seg text-ink shadow-seg" : "text-ink-4 hover:text-ink-2"
      }`}
    >
      {icon}
      <span className="sr-only">{label}</span>
    </button>
  );
}

function SunIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="4.2" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M12 2.6v2.2M12 19.2v2.2M4.2 12H2M22 12h-2.2M6.1 6.1 4.5 4.5M19.5 19.5l-1.6-1.6M17.9 6.1l1.6-1.6M4.5 19.5l1.6-1.6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M20.5 14.4A8.6 8.6 0 0 1 9.6 3.5a8.7 8.7 0 1 0 10.9 10.9Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}
