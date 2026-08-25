import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CardTile from "../components/CardTile";
import { useSetDetail } from "../lib/queries";

type Filter = "all" | "owned" | "needed";

export default function SetDetailPage() {
  const { ptcgSetId } = useParams<{ ptcgSetId: string }>();
  const { data: set, isLoading, error } = useSetDetail(ptcgSetId);
  const [filter, setFilter] = useState<Filter>("all");

  const cards = useMemo(() => {
    if (!set) return [];
    if (filter === "owned") return set.cards.filter((c) => c.is_owned);
    if (filter === "needed") return set.cards.filter((c) => !c.is_owned);
    return set.cards;
  }, [set, filter]);

  if (isLoading) return <p className="p-6 text-neutral-500">Loading...</p>;
  if (error) return <p className="p-6 text-red-600">Failed to load set: {String(error)}</p>;
  if (!set) return <p className="p-6 text-neutral-500">Set not found.</p>;

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{set.name}</h1>
          <p className="text-sm text-neutral-500">
            {set.owned_count} / {set.cards.length} owned
          </p>
        </div>
        <div className="flex items-center gap-2">
          <FilterButton active={filter === "all"} onClick={() => setFilter("all")}>
            All ({set.cards.length})
          </FilterButton>
          <FilterButton active={filter === "owned"} onClick={() => setFilter("owned")}>
            Owned ({set.owned_count})
          </FilterButton>
          <FilterButton active={filter === "needed"} onClick={() => setFilter("needed")}>
            Needed ({set.needed_count})
          </FilterButton>
          <Link
            to={`/sets/${set.ptcg_set_id}/entry`}
            className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-700"
          >
            Fast entry mode
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
        {cards.map((card) => (
          <CardTile key={card.id} card={card} />
        ))}
      </div>
    </div>
  );
}

function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
        active ? "bg-neutral-900 text-white" : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200"
      }`}
    >
      {children}
    </button>
  );
}
