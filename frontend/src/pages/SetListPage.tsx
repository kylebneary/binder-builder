import { Link } from "react-router-dom";
import { useSets } from "../lib/queries";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  Page,
  PageHeader,
} from "../components/ui";

export default function SetListPage() {
  const { data: sets, isLoading, error } = useSets();

  if (isLoading) return <LoadingState label="Loading sets" />;
  if (error) return <ErrorState message={`Failed to load sets: ${String(error)}`} />;

  return (
    <Page>
      <PageHeader
        title="Sets"
        subtitle={sets?.length ? `${sets.length} sets ingested` : undefined}
      />

      {!sets || sets.length === 0 ? (
        <EmptyState title="No sets ingested yet">
          Run <Mono>bb ingest cards --set sv8</Mono> to pull a set, then reload.
        </EmptyState>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
          {sets.map((s) => (
            <Link
              key={s.ptcg_set_id}
              to={`/sets/${s.ptcg_set_id}`}
              className="flex flex-col items-center gap-2.5 rounded-[11px] border border-line bg-raised p-4 text-center shadow-panel transition-colors hover:border-accent-line"
            >
              <div className="flex h-12 items-center justify-center">
                {s.logo_url ? (
                  <img
                    src={s.logo_url}
                    alt={s.name}
                    className="max-h-12 max-w-full object-contain"
                    loading="lazy"
                  />
                ) : (
                  <span className="text-[13px] font-medium text-ink-3">{s.name}</span>
                )}
              </div>
              <div className="text-[13px] font-semibold leading-tight text-ink">{s.name}</div>
              <div className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-ink-4">
                {s.series}
                {s.printed_total ? ` · ${s.printed_total} cards` : ""}
              </div>
            </Link>
          ))}
        </div>
      )}
    </Page>
  );
}
