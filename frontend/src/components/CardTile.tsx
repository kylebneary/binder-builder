import type { CardOut } from "../lib/types";
import { formatMoney } from "../lib/types";

/**
 * A single pocket in the card grid. Owned cards sit on the accent-tinted surface with a mono
 * OWNED tag; needed cards stay on the plain surface. Missing art falls back to the diagonal
 * card-back hatch used throughout the mockups.
 */
export default function CardTile({ card }: { card: CardOut }) {
  const canonical = card.variants.find((v) => v.is_canonical) ?? card.variants[0];

  return (
    <div
      className={`group flex flex-col overflow-hidden rounded-lg border p-2 text-center transition-colors ${
        card.is_owned
          ? "border-accent-line bg-accent-surface"
          : "border-line bg-raised hover:border-line-card"
      }`}
    >
      <div className="relative">
        {card.image_small ? (
          <img
            src={card.image_small}
            alt={card.name}
            className="mx-auto aspect-card w-full rounded bg-well object-cover"
            loading="lazy"
          />
        ) : (
          <div className="hatch flex aspect-card items-center justify-center rounded border border-line-card px-1">
            <span className="font-mono text-[9.5px] uppercase tracking-[0.06em] text-ink-3">
              No image
            </span>
          </div>
        )}
        {card.is_owned && (
          <span className="absolute right-1 top-1 rounded bg-canvas/80 px-1.5 py-[2px] font-mono text-[9.5px] font-medium text-accent-text">
            OWNED
          </span>
        )}
      </div>

      <div className="mt-1.5 flex flex-col gap-[1px]">
        <div className="truncate font-mono text-[10px] font-medium text-accent-text">
          {card.number}
        </div>
        <div className="truncate text-[11px] font-medium leading-tight text-ink-2" title={card.name}>
          {card.name}
        </div>
        <div className="truncate text-[10.5px] text-ink-3">{card.rarity ?? "—"}</div>
        {canonical && (
          <div className="font-mono text-[10.5px] font-medium text-ink-3">
            {formatMoney(canonical.market_price)}
          </div>
        )}
      </div>
    </div>
  );
}
