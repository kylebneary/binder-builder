import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Button,
  EmptyState,
  Field,
  Input,
  Page,
  PageHeader,
  Panel,
  SectionLabel,
  Segmented,
  Tag,
} from "../components/ui";
import { useCreateBinder, useBinders } from "../lib/queries";

/** The grid sizes docs/05-binder-spec.md commits to. Segmented was written for this switch. */
const GRIDS = [
  { value: "3x3", label: "3×3" },
  { value: "2x2", label: "2×2" },
  { value: "3x4", label: "3×4" },
  { value: "4x4", label: "4×4" },
] as const;

type Grid = (typeof GRIDS)[number]["value"];

function parseGrid(grid: Grid): { rows: number; cols: number } {
  const [rows, cols] = grid.split("x").map(Number);
  return { rows, cols };
}

export default function BindersPage() {
  const { data: binders, isLoading } = useBinders();
  const createBinder = useCreateBinder();

  const [name, setName] = useState("");
  const [grid, setGrid] = useState<Grid>("3x3");
  const [pages, setPages] = useState(20);
  const [sideLoading, setSideLoading] = useState(true);

  const canSubmit = name.trim().length > 0 && pages > 0;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    createBinder.mutate(
      { name: name.trim(), ...parseGrid(grid), pages, is_side_loading: sideLoading },
      { onSuccess: () => setName("") },
    );
  }

  return (
    <Page width="narrow">
      <PageHeader
        title="Binders"
        subtitle="Plan a physical binder page by page, then print the inserts"
      />

      <Panel className="mb-6 p-4">
        <SectionLabel className="mb-3.5">New binder</SectionLabel>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
          <div className="flex flex-col gap-3.5 sm:flex-row sm:items-end">
            <div className="flex-1">
              <Field label="Name">
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Surging Sparks master"
                />
              </Field>
            </div>
            <div className="sm:w-28">
              <Field label="Pages">
                <Input
                  type="number"
                  min={1}
                  value={pages}
                  onChange={(e) => setPages(Number(e.target.value))}
                />
              </Field>
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-5">
            <div className="flex flex-col gap-1.5">
              <span className="text-[12.5px] font-medium text-ink-2">Pocket grid</span>
              <Segmented
                value={grid}
                onChange={(v) => setGrid(v)}
                options={GRIDS.map((g) => ({ value: g.value, label: g.label }))}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="text-[12.5px] font-medium text-ink-2">Page loading</span>
              <Segmented
                value={sideLoading ? "side" : "top"}
                onChange={(v) => setSideLoading(v === "side")}
                options={[
                  { value: "side", label: "Side" },
                  { value: "top", label: "Top" },
                ]}
              />
            </div>

            <div className="flex-1" />
            <Button type="submit" disabled={!canSubmit || createBinder.isPending}>
              {createBinder.isPending ? "Creating..." : "Create binder"}
            </Button>
          </div>

          {!sideLoading && (
            <p className="text-[11.5px] text-ink-3">
              Top-loading pages cannot hold artwork that crosses the gutter &mdash; the pocket lip
              cuts across it, so those placements are refused.
            </p>
          )}
        </form>
        {createBinder.isError && (
          <p className="mt-3 text-[12px] text-danger-text">
            {(createBinder.error as Error).message}
          </p>
        )}
      </Panel>

      {isLoading ? (
        <p className="font-mono text-[12px] uppercase tracking-[0.08em] text-ink-3">
          Loading binders
        </p>
      ) : !binders || binders.length === 0 ? (
        <EmptyState title="No binders yet">
          Create one above, then drag cards into its pockets.
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-2">
          {binders.map((b) => (
            <Link
              key={b.id}
              to={`/binders/${b.id}`}
              className="flex items-center justify-between gap-4 rounded-[11px] border border-line bg-raised px-4 py-3.5 shadow-panel transition-colors hover:border-accent-line"
            >
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-[13.5px] font-semibold text-ink">{b.name}</span>
                <span className="text-[11.5px] text-ink-3">
                  {b.rows}&times;{b.cols} &middot; {b.pages} pages &middot;{" "}
                  {b.is_side_loading ? "side-loading" : "top-loading"}
                </span>
              </div>
              <Tag tone="accent">{b.rows * b.cols * b.pages} POCKETS</Tag>
            </Link>
          ))}
        </div>
      )}
    </Page>
  );
}
