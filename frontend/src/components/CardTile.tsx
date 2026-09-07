import type { CardOut } from "../lib/types";
import { formatMoney } from "../lib/types";

/**
 * A single pocket in a card grid. Owned cards sit on the accent-tinted surface with a mono
 * OWNED tag; needed cards stay on the plain surface. Missing art falls back to the diagonal
 * card-back hatch used throughout the mockups.
 *
 * `CardTileBase` is the presentation; the default export adapts a set-browse `CardOut` onto it.
 * The portfolio holdings grid passes its own fields plus the optional badges (variant, quantity,
 * condition, location) that only make sense for something you actually own.
 */
export function CardTileBase({
  name,
  number,
  rarity,
  imageSmall,
  price,
  owned,
  variantLabel,
  quantity,
  condition,
  location,
}: {
  name: string;
  number: string;
  rarity: string | null;
  imageSmall: string | null;
  price: string | null;
  owned: boolean;
  /** Printing (Normal / Reverse Holofoil / ...) -- shown only when supplied. */
  variantLabel?: string;
  /** Rendered as a xN badge over the art when it is more than one -- a x1 on every tile in a
   * collection of singles is noise, so a plain tile just reads as "owned". */
  quantity?: number;
  /** Shown only when it is not NM. 96% of a typical collection is NM, so badging it everywhere
   * drowns the 4% that actually wants attention -- the same reason a x1 badge is suppressed. */
  condition?: string;
  /** Where the card physically is. The whole point of the holdings view, so it gets a line of
   * its own rather than a hover title. */
  location?: string | null;
}) {
  // Two modes. A set-browse tile (no quantity) tags what you own; a holdings tile is all owned
  // already, so it only speaks up when you have more than one.
  let badge: string | null = null;
  if (quantity === undefined) badge = owned ? "OWNED" : null;
  else if (quantity !== 1) badge = `x${quantity}`;

  return (
    <div
      className={`group flex flex-col overflow-hidden rounded-lg border p-2 text-center transition-colors ${
        owned
          ? "border-accent-line bg-accent-surface"
          : "border-line bg-raised hover:border-line-card"
      }`}
    >
      <div className="relative">
        {imageSmall ? (
          <img
            src={imageSmall}
            alt={name}
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
        {badge && (
          <span className="absolute right-1 top-1 rounded bg-canvas/80 px-1.5 py-[2px] font-mono text-[9.5px] font-medium text-accent-text">
            {badge}
          </span>
        )}
        {condition && condition !== "NM" && (
          <span className="absolute left-1 top-1 rounded bg-canvas/80 px-1.5 py-[2px] font-mono text-[9.5px] font-medium text-ink-3">
            {condition}
          </span>
        )}
      </div>

      <div className="mt-1.5 flex flex-col gap-[1px]">
        <div className="truncate font-mono text-[10px] font-medium text-accent-text">{number}</div>
        <div className="truncate text-[11px] font-medium leading-tight text-ink-2" title={name}>
          {name}
        </div>
        <div className="truncate text-[10.5px] text-ink-3" title={variantLabel ?? rarity ?? ""}>
          {variantLabel ?? rarity ?? "—"}
        </div>
        <div className="font-mono text-[10.5px] font-medium text-ink-3">{formatMoney(price)}</div>
        {location !== undefined && (
          <div className="truncate font-mono text-[10px] text-ink-4" title={location ?? ""}>
            {location ?? "—"}
          </div>
        )}
      </div>
    </div>
  );
}

export default function CardTile({ card }: { card: CardOut }) {
  const canonical = card.variants.find((v) => v.is_canonical) ?? card.variants[0];

  return (
    <CardTileBase
      name={card.name}
      number={card.number}
      rarity={card.rarity}
      imageSmall={card.image_small}
      price={canonical?.market_price ?? null}
      owned={card.is_owned}
    />
  );
}
