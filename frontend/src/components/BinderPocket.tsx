import { useDraggable, useDroppable } from "@dnd-kit/core";
import type { CSSProperties } from "react";
import type { PlacementOut } from "../lib/types";
import { Tag } from "./ui";

/**
 * One pocket of the grid: a droppable cell that may hold a draggable card.
 *
 * Built from CardTile's markup rather than fresh styling -- same art treatment, same hatch
 * placeholder, same mono number label. The difference is the aspect ratio: a tile is the card
 * (63x88), a pocket is the sleeve opening that holds it (aspect-pocket), so the spread reads at
 * the proportions a collector would see in the real binder.
 */

export function pocketId(pageIndex: number, row: number, col: number) {
  return `pocket:${pageIndex}:${row}:${col}`;
}

export function parsePocketId(id: string) {
  const [, page, row, col] = id.split(":");
  return { pageIndex: Number(page), row: Number(row), col: Number(col) };
}

/** The visual body of a placed card. Shared with the drag overlay so the card being dragged
 * looks exactly like the card in the pocket. */
export function PlacedCard({ placement }: { placement: PlacementOut }) {
  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden rounded-[5px]">
      {placement.image_small ? (
        <img
          src={placement.image_small}
          alt={placement.card_name ?? "Card"}
          className="h-full w-full rounded-[5px] object-cover"
          loading="lazy"
          draggable={false}
        />
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-0.5 rounded-[5px] bg-well px-1 text-center">
          <span className="font-mono text-[9.5px] font-medium text-accent-text">
            {placement.number}
          </span>
          <span className="truncate text-[10px] leading-tight text-ink-2">
            {placement.card_name}
          </span>
        </div>
      )}

      {!placement.is_owned && (
        <span className="absolute left-1 top-1">
          <Tag tone="warn">NEED</Tag>
        </span>
      )}
    </div>
  );
}

export default function BinderPocket({
  pageIndex,
  row,
  col,
  placement,
  style,
  onRemove,
}: {
  pageIndex: number;
  row: number;
  col: number;
  placement?: PlacementOut;
  style?: CSSProperties;
  onRemove?: (placement: PlacementOut) => void;
}) {
  const id = pocketId(pageIndex, row, col);
  const { setNodeRef: setDropRef, isOver } = useDroppable({ id });

  const {
    attributes,
    listeners,
    setNodeRef: setDragRef,
    isDragging,
  } = useDraggable({
    // Keyed by cell, not by placement id. dnd-kit registers every draggable in a map keyed by
    // id, so an empty pocket falling back to a shared literal (every empty pocket claiming
    // "placement:none") would collapse seventeen nodes onto one registry entry.
    id: `drag:${id}`,
    data: { placementId: placement?.id, from: { pageIndex, row, col } },
    disabled: !placement,
  });

  return (
    <div
      ref={setDropRef}
      style={style}
      className={`group/pocket aspect-pocket relative rounded-md border p-[3px] transition-colors ${
        isOver
          ? "border-accent bg-accent-surface"
          : placement
            ? "border-line-card bg-raised"
            : "hatch border-line"
      }`}
    >
      {placement ? (
        <>
          <div
            ref={setDragRef}
            {...listeners}
            {...attributes}
            role="button"
            aria-label={`${placement.number ?? ""} ${placement.card_name ?? "placement"}, page ${
              pageIndex + 1
            } row ${row + 1} column ${col + 1}`}
            className={`h-full w-full cursor-grab touch-none active:cursor-grabbing ${
              isDragging ? "opacity-25" : ""
            }`}
          >
            <PlacedCard placement={placement} />
          </div>
          {onRemove && (
            <button
              type="button"
              onClick={() => onRemove(placement)}
              aria-label={`Remove ${placement.card_name ?? "placement"} from the binder`}
              className="absolute right-[3px] top-[3px] hidden rounded bg-canvas/85 px-1.5 py-[1px] font-mono text-[11px] font-medium leading-tight text-ink-3 hover:text-danger-text focus-visible:block group-hover/pocket:block"
            >
              &times;
            </button>
          )}
        </>
      ) : (
        <span className="sr-only">
          Empty pocket, page {pageIndex + 1} row {row + 1} column {col + 1}
        </span>
      )}
    </div>
  );
}
