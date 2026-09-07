import type { CSSProperties } from "react";
import type { BinderLayoutOut, PlacementOut } from "../lib/types";
import BinderPocket from "./BinderPocket";

/**
 * Two facing pages drawn as one grid, at true aspect ratio.
 *
 * The whole spread is a single CSS grid of `2*cols + 1` columns: the extra middle column is the
 * physical gutter, sized as a fraction of a pocket width (gutter_mm / POCKET_W_MM) so the gap on
 * screen is proportionally the gap in the binder. Drawing both pages in one grid -- rather than
 * two grids side by side -- is what lets a gutter-spanning insert occupy a single rectangle that
 * genuinely crosses the gutter, matching how the backend stores it.
 *
 * Column mapping mirrors `backend/app/binder/layout.py`:
 *   left page  (even), col c  -> grid column c + 1
 *   right page (odd),  col c  -> grid column c + cols + 2   (+1 for the gutter column)
 *   gutter-spanning, spread col c -> starts at c + 1 and its span absorbs the gutter column
 */

const POCKET_W_MM = 70;

function gridColumnFor(
  placement: Pick<PlacementOut, "page_index" | "col" | "col_span" | "spans_gutter">,
  cols: number,
): string {
  if (placement.spans_gutter) {
    const start = placement.col + 1;
    // +1 absorbs the gutter column the rectangle crosses.
    return `${start} / span ${placement.col_span + 1}`;
  }
  const offset = placement.page_index % 2 === 0 ? 1 : cols + 2;
  return `${placement.col + offset} / span ${placement.col_span}`;
}

export default function SpreadView({
  layout,
  spreadIndex,
  onRemove,
}: {
  layout: BinderLayoutOut;
  spreadIndex: number;
  onRemove?: (placement: PlacementOut) => void;
}) {
  const { rows, cols, gutter_mm } = layout;
  const leftPage = spreadIndex * 2;
  const rightPage = leftPage + 1;

  const onSpread = layout.placements.filter(
    (p) => p.page_index === leftPage || p.page_index === rightPage,
  );
  const byCell = new Map<string, PlacementOut>();
  for (const p of onSpread) {
    if (!p.spans_gutter) byCell.set(`${p.page_index}:${p.row}:${p.col}`, p);
  }
  const spanning = onSpread.filter((p) => p.spans_gutter);

  const style: CSSProperties = {
    display: "grid",
    gridTemplateColumns: `repeat(${cols}, 1fr) ${gutter_mm / POCKET_W_MM}fr repeat(${cols}, 1fr)`,
    gap: "6px",
  };

  const pockets = [];
  for (const pageIndex of [leftPage, rightPage]) {
    const beyondEnd = pageIndex >= layout.pages;
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const offset = pageIndex % 2 === 0 ? 1 : cols + 2;
        if (beyondEnd) {
          // The binder has an odd page count and this half of the spread does not exist.
          pockets.push(
            <div
              key={`void:${pageIndex}:${row}:${col}`}
              aria-hidden="true"
              style={{ gridColumn: col + offset, gridRow: row + 1 }}
              className="aspect-pocket rounded-md border border-dashed border-line opacity-40"
            />,
          );
          continue;
        }
        pockets.push(
          <BinderPocket
            key={`${pageIndex}:${row}:${col}`}
            pageIndex={pageIndex}
            row={row}
            col={col}
            placement={byCell.get(`${pageIndex}:${row}:${col}`)}
            style={{ gridColumn: col + offset, gridRow: row + 1 }}
            onRemove={onRemove}
          />,
        );
      }
    }
  }

  return (
    <div>
      <div style={style}>
        {pockets}
        {spanning.map((p) => (
          <div
            key={`span:${p.id}`}
            style={{
              gridColumn: gridColumnFor(p, cols),
              gridRow: `${p.row + 1} / span ${p.row_span}`,
            }}
            className="flex items-center justify-center rounded-md border border-accent-line bg-accent-surface p-[3px]"
          >
            <span className="font-mono text-[10.5px] font-medium text-accent-text">
              insert #{p.insert_asset_id ?? "—"}
            </span>
          </div>
        ))}
      </div>

      <div
        className="mt-2 grid text-center"
        style={{ ...style, gap: "6px" }}
        aria-hidden="true"
      >
        <span
          className="label-mono"
          style={{ gridColumn: `1 / span ${cols}` }}
        >
          Page {leftPage + 1}
        </span>
        <span
          className="label-mono"
          style={{ gridColumn: `${cols + 2} / span ${cols}` }}
        >
          {rightPage < layout.pages ? `Page ${rightPage + 1}` : "—"}
        </span>
      </div>
    </div>
  );
}
