import type { CardOut } from "../lib/types";
import { formatMoney } from "../lib/types";

export default function CardTile({ card }: { card: CardOut }) {
  const canonical = card.variants.find((v) => v.is_canonical) ?? card.variants[0];

  return (
    <div
      className={`flex flex-col rounded-lg border p-2 text-center transition ${
        card.is_owned
          ? "border-emerald-300 bg-emerald-50"
          : "border-neutral-200 bg-white hover:border-neutral-400"
      }`}
    >
      <div className="relative">
        {card.image_small ? (
          <img
            src={card.image_small}
            alt={card.name}
            className="mx-auto aspect-[63/88] w-full rounded bg-neutral-100 object-cover"
            loading="lazy"
          />
        ) : (
          <div className="flex aspect-[63/88] items-center justify-center rounded bg-neutral-100 text-xs text-neutral-400">
            {card.name}
          </div>
        )}
        {card.is_owned && (
          <span className="absolute right-1 top-1 rounded-full bg-emerald-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
            OWNED
          </span>
        )}
      </div>
      <div className="mt-1 truncate text-xs font-medium text-neutral-800" title={card.name}>
        #{card.number} {card.name}
      </div>
      <div className="text-[11px] text-neutral-500">{card.rarity ?? "—"}</div>
      {canonical && (
        <div className="text-[11px] text-neutral-600">{formatMoney(canonical.market_price)}</div>
      )}
    </div>
  );
}
