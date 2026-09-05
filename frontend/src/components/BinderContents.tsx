import { Table, Tag, Td, Th, Tr } from "./ui";
import type { BinderLayoutOut, PlacementOut } from "../lib/types";

/**
 * Everything in the binder as a flat list, in page order.
 *
 * The spread view answers "what does this page look like"; this answers "what is in here, and
 * what am I missing" -- the questions the portfolio table answers for the collection. It is also
 * the discoverable way to remove a placement: the per-pocket close button only appears on hover,
 * which is fine as a shortcut but is not something a first-time user finds.
 */

/** Pocket address in the way collectors read a page: row as a letter, column as a number. */
function pocketLabel(p: PlacementOut) {
  return `${String.fromCharCode(65 + p.row)}${p.col + 1}`;
}

export default function BinderContents({
  layout,
  spreadIndex,
  onJumpToSpread,
  onRemove,
}: {
  layout: BinderLayoutOut;
  spreadIndex: number;
  onJumpToSpread: (spreadIndex: number) => void;
  onRemove: (placement: PlacementOut) => void;
}) {
  const rows = [...layout.placements].sort(
    (a, b) => a.page_index - b.page_index || a.row - b.row || a.col - b.col,
  );

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="label-mono">Contents</span>
        <div className="flex-1" />
        <span className="font-mono text-[11px] text-ink-3">
          {layout.placements.length} placed
          {layout.not_owned_count > 0 && ` · ${layout.not_owned_count} not owned`}
        </span>
      </div>

      <div className="max-h-[70vh] overflow-y-auto">
        <Table
          head={
            <>
              <Th className="w-16 px-2.5">Page</Th>
              <Th className="w-10 px-1">#</Th>
              <Th className="px-2">Card</Th>
              <Th className="w-8 px-1" aria-label="Remove" />
            </>
          }
        >
          {rows.length === 0 ? (
            <Tr>
              <Td colSpan={4} className="py-8 text-center text-ink-3">
                Nothing placed yet — drag a card from the pool, or use Fill binder.
              </Td>
            </Tr>
          ) : (
            rows.map((p) => {
              const onThisSpread = Math.floor(p.page_index / 2) === spreadIndex;
              return (
                <Tr key={p.id} highlight={onThisSpread}>
                  <Td className="px-2.5">
                    <button
                      type="button"
                      onClick={() => onJumpToSpread(Math.floor(p.page_index / 2))}
                      className="whitespace-nowrap rounded font-mono text-[11px] font-medium text-accent-text hover:underline"
                      aria-label={`Go to page ${p.page_index + 1}, pocket ${pocketLabel(p)}`}
                    >
                      {p.page_index + 1}&#8202;·&#8202;{pocketLabel(p)}
                    </button>
                  </Td>
                  <Td className="px-1 font-mono text-[11px] text-ink-3">{p.number ?? "—"}</Td>
                  <Td className="px-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-ink" title={p.card_name ?? undefined}>
                        {p.kind === "insert"
                          ? `Insert #${p.insert_asset_id ?? "—"}`
                          : (p.card_name ?? "—")}
                      </span>
                      {p.kind === "card" && !p.is_owned && <Tag tone="warn">NEED</Tag>}
                      {p.spans_gutter && <Tag tone="accent">GUTTER</Tag>}
                    </div>
                    {p.rarity && (
                      <div className="truncate text-[11px] text-ink-3">
                        {p.rarity}
                        {p.variant && p.variant !== "normal" ? ` · ${p.variant}` : ""}
                      </div>
                    )}
                  </Td>
                  <Td className="px-1 text-right align-middle">
                    <button
                      type="button"
                      onClick={() => onRemove(p)}
                      title="Remove from binder"
                      className="rounded px-1.5 py-1 text-[15px] leading-none text-ink-4 transition-colors hover:bg-danger-surface hover:text-danger-text"
                      aria-label={`Remove ${p.card_name ?? "placement"} from the binder`}
                    >
                      &times;
                    </button>
                  </Td>
                </Tr>
              );
            })
          )}
        </Table>
      </div>
    </div>
  );
}
