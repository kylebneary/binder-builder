import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import CardTile from "../components/CardTile";
import { useSetDetail } from "../lib/queries";
import {
  ButtonLink,
  EmptyState,
  ErrorState,
  LoadingState,
  Page,
  PageHeader,
  ProgressBar,
  Segmented,
} from "../components/ui";

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

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={`Failed to load set: ${String(error)}`} />;
  if (!set) return <ErrorState message="Set not found." />;

  const completion = set.cards.length > 0 ? set.owned_count / set.cards.length : 0;

  return (
    <Page>
      <PageHeader
        title={set.name}
        subtitle={
          <>
            {set.series} · {set.owned_count} / {set.cards.length} owned
          </>
        }
        back={{ to: "/", label: "Sets" }}
      >
        <Segmented<Filter>
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: `ALL ${set.cards.length}` },
            { value: "owned", label: `OWNED ${set.owned_count}` },
            { value: "needed", label: `NEEDED ${set.needed_count}` },
          ]}
        />
        <ButtonLink to={`/sets/${set.ptcg_set_id}/entry`}>Fast entry</ButtonLink>
      </PageHeader>

      <div className="mb-5 flex items-center gap-3">
        <ProgressBar value={completion} className="flex-1" />
        <span className="font-mono text-[11px] font-medium text-accent-text">
          {(completion * 100).toFixed(0)}%
        </span>
      </div>

      {cards.length === 0 ? (
        <EmptyState title={filter === "owned" ? "Nothing owned yet" : "Nothing left to find"}>
          {filter === "owned"
            ? "Quantities entered in fast entry mode show up here."
            : "Every card in this set is already in the collection."}
        </EmptyState>
      ) : (
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-9">
          {cards.map((card) => (
            <CardTile key={card.id} card={card} />
          ))}
        </div>
      )}
    </Page>
  );
}
