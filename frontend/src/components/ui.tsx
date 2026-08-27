/**
 * Shared primitives for the "Dark studio / Warm paper" design system.
 *
 * Every screen is assembled from these so the two themes stay consistent: no component below
 * names a raw colour, only the semantic Tailwind tokens backed by CSS variables. Sizes and
 * radii come straight from the Claude Design mockups (11px panels, 9px buttons, 6px chips).
 */
import { Link } from "react-router-dom";

type Div = React.HTMLAttributes<HTMLDivElement>;

function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ layout */

/** Standard page wrapper: centred column over the canvas glow (dark) / flat paper (light). */
export function Page({
  children,
  width = "wide",
}: {
  children: React.ReactNode;
  width?: "wide" | "narrow";
}) {
  return (
    <div className="min-h-[calc(100vh-56px)] bg-glow">
      <div
        className={cx("mx-auto px-6 py-6 sm:px-8", width === "narrow" ? "max-w-4xl" : "max-w-7xl")}
      >
        {children}
      </div>
    </div>
  );
}

/** Page title block -- title plus a muted one-line subtitle, as in every mockup header. */
export function PageHeader({
  title,
  subtitle,
  back,
  children,
}: {
  title: string;
  subtitle?: React.ReactNode;
  back?: { to: string; label: string; onClick?: (e: React.MouseEvent) => void };
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end gap-4">
      <div className="flex min-w-0 flex-col gap-1">
        {back && (
          <Link
            to={back.to}
            onClick={back.onClick}
            className="mb-0.5 w-fit text-[12.5px] font-medium text-ink-3 transition-colors hover:text-ink"
          >
            &larr; {back.label}
          </Link>
        )}
        <h1 className="text-[19px] font-semibold tracking-[-0.2px] text-ink">{title}</h1>
        {subtitle && <p className="text-[12.5px] text-ink-3">{subtitle}</p>}
      </div>
      <div className="flex-1" />
      {children && <div className="flex flex-wrap items-center gap-2.5">{children}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ panels */

export function Panel({ className, children, ...rest }: Div) {
  return (
    <div
      className={cx("rounded-[11px] border border-line bg-raised shadow-panel", className)}
      {...rest}
    >
      {children}
    </div>
  );
}

/** The tinted "here is the answer" panel -- dry-run summary, cheapest path, best strategy. */
export function AccentPanel({ className, children, ...rest }: Div) {
  return (
    <div
      className={cx("rounded-[11px] border border-accent-line bg-accent-panel", className)}
      {...rest}
    >
      {children}
    </div>
  );
}

/** Small uppercase mono section label used throughout the mockups. */
export function SectionLabel({ className, children, ...rest }: Div) {
  return (
    <div className={cx("label-mono", className)} {...rest}>
      {children}
    </div>
  );
}

/* ----------------------------------------------------------------- controls */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-[9px] px-4 py-2.5 text-[13px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg hover:opacity-90",
  secondary: "border border-line-strong bg-raised text-ink-2 hover:border-line-card hover:text-ink",
  danger: "border border-danger-line bg-danger-surface text-danger-text hover:opacity-90",
  ghost: "text-ink-3 hover:text-ink",
};

export function Button({
  variant = "primary",
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={cx(BUTTON_BASE, BUTTON_VARIANTS[variant], className)} {...rest} />;
}

export function ButtonLink({
  variant = "primary",
  className,
  ...rest
}: React.ComponentProps<typeof Link> & { variant?: ButtonVariant }) {
  return <Link className={cx(BUTTON_BASE, BUTTON_VARIANTS[variant], className)} {...rest} />;
}

/** Mono chip: the filter/status pills in the row report and constraint panels. */
export function Chip({
  active,
  tone = "accent",
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  active?: boolean;
  tone?: "accent" | "warn" | "neutral";
}) {
  const activeClass =
    tone === "warn"
      ? "bg-warn text-warn-fg"
      : tone === "neutral"
        ? "bg-track text-ink"
        : "bg-accent text-accent-fg";
  return (
    <button
      className={cx(
        "rounded-md px-2.5 py-[5px] font-mono text-[11px] font-medium transition-colors",
        active ? activeClass : "border border-line-strong bg-raised text-ink-3 hover:text-ink",
        className,
      )}
      {...rest}
    />
  );
}

/** Static (non-interactive) status tag: AUTO / SKIP / matched / no_set / OWNED. */
export function Tag({
  tone = "neutral",
  className,
  children,
}: {
  tone?: "accent" | "warn" | "neutral" | "danger";
  className?: string;
  children: React.ReactNode;
}) {
  const tones = {
    accent: "bg-accent-surface text-accent-text",
    warn: "bg-warn-surface text-warn-text",
    danger: "bg-danger-surface text-danger-text",
    neutral: "bg-inset text-ink-3",
  } as const;
  return (
    <span
      className={cx(
        "inline-block rounded px-1.5 py-[3px] font-mono text-[10.5px] font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Segmented control -- the 3x3 / 3x4 / 2x2 and NM / LP / ANY switches. */
export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  className,
}: {
  value: T;
  options: { value: T; label: React.ReactNode }[];
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div
      className={cx("inline-flex gap-[5px] rounded-lg border border-line bg-inset p-[3px]", className)}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.value)}
            className={cx(
              "rounded-[5px] px-2.5 py-1.5 font-mono text-[11.5px] font-medium transition-colors",
              active ? "bg-seg text-ink shadow-seg" : "text-ink-3 hover:text-ink-2",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------- fields */

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[12.5px] font-medium text-ink-2">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-ink-3">{hint}</span>}
    </label>
  );
}

const CONTROL =
  "w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-[13px] text-ink outline-none transition-colors placeholder:text-ink-4 focus:border-accent focus:shadow-glow";

export function Input({ className, ...rest }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx(CONTROL, className)} {...rest} />;
}

export function Select({ className, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cx(CONTROL, "cursor-pointer", className)} {...rest} />;
}

/* -------------------------------------------------------------- data display */

export function ProgressBar({
  value,
  tone = "accent",
  className,
}: {
  /** 0..1 */
  value: number;
  tone?: "accent" | "muted";
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cx("h-1 overflow-hidden rounded-full bg-track", className)}
    >
      <div
        className={cx("h-full transition-[width]", tone === "muted" ? "bg-track-muted" : "bg-accent")}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/** Two-segment split bar -- singles vs sealed, matched vs unmatched. */
export function SplitBar({
  left,
  className,
}: {
  /** Share of the bar given to the accent segment, 0..1. */
  left: number;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, left)) * 100;
  return (
    <div
      role="img"
      aria-label={`${Math.round(pct)}% singles, ${100 - Math.round(pct)}% sealed`}
      className={cx("flex h-1.5 overflow-hidden rounded-full bg-track", className)}
    >
      <div className="bg-accent" style={{ width: `${pct}%` }} />
      <div className="bg-warn" style={{ width: `${100 - pct}%` }} />
    </div>
  );
}

export function Stat({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "negative";
  hint?: string;
}) {
  const toneClass =
    tone === "positive" ? "text-accent-text" : tone === "negative" ? "text-danger-text" : "text-ink";
  return (
    <Panel className="flex flex-col gap-1.5 p-4">
      <SectionLabel>{label}</SectionLabel>
      <div className={cx("font-mono text-[22px] font-bold tracking-[-0.5px]", toneClass)}>
        {value}
      </div>
      {hint && <div className="text-[11px] text-ink-3">{hint}</div>}
    </Panel>
  );
}

/** Inline note: pull-rate caveats, unpriced cards, coverage gaps. */
export function Callout({
  tone = "warn",
  className,
  children,
}: {
  tone?: "warn" | "accent" | "danger";
  className?: string;
  children: React.ReactNode;
}) {
  const tones = {
    warn: "border-warn-line bg-warn-surface text-warn-text",
    accent: "border-accent-line bg-accent-surface text-accent-text",
    danger: "border-danger-line bg-danger-surface text-danger-text",
  } as const;
  return (
    <div
      className={cx("rounded-lg border px-3.5 py-2.5 text-[12px] leading-[1.55]", tones[tone], className)}
    >
      {children}
    </div>
  );
}

/* -------------------------------------------------------------- page states */

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2.5 px-6 py-16 text-ink-3">
      <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
      <span className="font-mono text-[12px] uppercase tracking-[0.08em]">{label}</span>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div role="alert" className="px-6 py-16">
      <Callout tone="danger" className="max-w-xl">
        {message}
      </Callout>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <Panel className="flex flex-col items-center gap-2 px-6 py-14 text-center">
      <div className="text-[14px] font-semibold text-ink-2">{title}</div>
      {children && <div className="max-w-md text-[12.5px] leading-[1.6] text-ink-3">{children}</div>}
    </Panel>
  );
}

/** Inline code / literal, mono on an inset chip -- used for CLI hints and field names. */
export function Mono({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[11.5px] text-ink-2">
      {children}
    </code>
  );
}

/* -------------------------------------------------------------------- table */

export function Table({ head, children }: { head: React.ReactNode; children: React.ReactNode }) {
  return (
    <Panel className="overflow-hidden p-0">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-line bg-surface text-left">{head}</tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </Panel>
  );
}

export function Th({ className, children, ...rest }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cx(
        "whitespace-nowrap px-3.5 py-2.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-3",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function Td({ className, children, ...rest }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cx("px-3.5 py-2.5 text-ink-2", className)} {...rest}>
      {children}
    </td>
  );
}

export function Tr({
  highlight,
  className,
  children,
}: {
  highlight?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <tr className={cx("border-b border-line last:border-0", highlight && "bg-accent-surface", className)}>
      {children}
    </tr>
  );
}
