import { Link } from "react-router-dom";
import { useSets } from "../lib/queries";

export default function SetListPage() {
  const { data: sets, isLoading, error } = useSets();

  if (isLoading) return <p className="p-6 text-neutral-500">Loading sets...</p>;
  if (error) return <p className="p-6 text-red-600">Failed to load sets: {String(error)}</p>;
  if (!sets || sets.length === 0) {
    return (
      <p className="p-6 text-neutral-500">
        No sets yet. Run <code className="rounded bg-neutral-100 px-1">bb ingest cards --set sv8</code>{" "}
        to pull some.
      </p>
    );
  }

  return (
    <div className="mx-auto max-w-6xl p-6">
      <h1 className="mb-4 text-xl font-semibold">Sets</h1>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
        {sets.map((s) => (
          <Link
            key={s.ptcg_set_id}
            to={`/sets/${s.ptcg_set_id}`}
            className="flex flex-col items-center gap-2 rounded-lg border border-neutral-200 bg-white p-4 text-center transition hover:border-neutral-400 hover:shadow-sm"
          >
            {s.logo_url ? (
              <img src={s.logo_url} alt={s.name} className="h-12 max-w-full object-contain" />
            ) : (
              <div className="flex h-12 items-center text-sm text-neutral-400">{s.name}</div>
            )}
            <div className="text-sm font-medium text-neutral-800">{s.name}</div>
            <div className="text-xs text-neutral-500">
              {s.series} {s.printed_total ? `· ${s.printed_total} cards` : ""}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
