import ThemeToggle from "./ThemeToggle";

/**
 * Nav for the standalone binder-designer demo (VITE_DEMO_MODE), used instead of the real Nav.
 *
 * The real Nav links to Sets/Portfolio/Goals/Binders, none of which demoApi.ts implements --
 * this demo is scoped to one seeded binder, so it says as much and points back to the repo
 * instead of offering links that would land on a page with no data behind it.
 */
export default function DemoNav() {
  return (
    <header className="sticky top-0 z-20 h-14 border-b border-line bg-surface">
      <div className="mx-auto flex h-full max-w-[1600px] items-center gap-3 px-5 sm:px-6">
        <span
          aria-hidden="true"
          className="h-[26px] w-5 flex-none rounded-[3px] bg-gradient-to-br from-accent to-accent-deep"
        />
        <span className="text-[15px] font-semibold tracking-[-0.2px] text-ink">
          binder&#8203;-builder
        </span>
        <span className="rounded-full bg-accent-surface px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-accent-text">
          Demo
        </span>
        <span className="hidden text-[12px] text-ink-3 sm:inline">
          One seeded binder, running entirely in your browser &mdash; no backend, no account.
        </span>
        <div className="flex-1" />
        <a
          href="https://github.com/kylebneary/binder-builder"
          target="_blank"
          rel="noopener"
          className="text-[12.5px] font-medium text-ink-3 transition-colors hover:text-ink"
        >
          Source
        </a>
        <ThemeToggle />
      </div>
    </header>
  );
}
