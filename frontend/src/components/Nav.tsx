import { Link } from "react-router-dom";
import { usePortfolio } from "../lib/queries";
import { formatMoney } from "../lib/types";

export default function Nav() {
  const { data: portfolio } = usePortfolio();

  return (
    <header className="border-b border-neutral-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <Link to="/" className="text-lg font-semibold text-neutral-900">
          binder-builder
        </Link>
        {portfolio && (
          <Link to="/portfolio" className="text-sm text-neutral-600 hover:text-neutral-900">
            Portfolio value:{" "}
            <span className="font-medium text-neutral-900">
              {formatMoney(portfolio.total_market_value)}
            </span>
          </Link>
        )}
      </div>
    </header>
  );
}
