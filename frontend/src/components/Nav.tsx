import { NavLink } from "react-router-dom";
import { usePortfolio } from "../lib/queries";
import { formatMoney } from "../lib/types";
import ThemeToggle from "./ThemeToggle";

const LINKS = [
  { to: "/", label: "Sets", end: true },
  { to: "/portfolio", label: "Portfolio", end: false },
  { to: "/goals", label: "Goals", end: false },
];

export default function Nav() {
  const { data: portfolio } = usePortfolio();

  return (
    <header className="sticky top-0 z-20 h-14 border-b border-line bg-surface">
      <div className="mx-auto flex h-full max-w-[1600px] items-center gap-6 px-5 sm:px-6">
        <NavLink to="/" className="flex flex-none items-center gap-2.5">
          {/* Card-shaped mark: the accent gradient from the mockup logo. */}
          <span
            aria-hidden="true"
            className="h-[26px] w-5 rounded-[3px] bg-gradient-to-br from-accent to-accent-deep"
          />
          <span className="text-[15px] font-semibold tracking-[-0.2px] text-ink">
            binder&#8203;-builder
          </span>
        </NavLink>

        <nav className="flex items-center gap-1">
          {LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                `rounded-[7px] px-3 py-[7px] text-[13px] font-medium transition-colors ${
                  isActive ? "bg-nav-active text-ink" : "text-ink-3 hover:text-ink-2"
                }`
              }
            >
              {l.label}
            </NavLink>
          ))}
        </nav>

        <div className="flex-1" />

        {portfolio && (
          <NavLink
            to="/portfolio"
            className="hidden font-mono text-[11px] font-medium uppercase tracking-[0.04em] text-ink-3 transition-colors hover:text-ink sm:block"
          >
            Portfolio{" "}
            <span className="text-ink">{formatMoney(portfolio.total_market_value)}</span>
          </NavLink>
        )}

        <ThemeToggle />
      </div>
    </header>
  );
}
