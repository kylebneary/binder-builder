import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type {
  CollectionItemIn,
  CollectionItemOut,
  PortfolioSummaryOut,
  SetDetailOut,
  SetOut,
} from "./types";

export function useSets() {
  return useQuery({
    queryKey: ["sets"],
    queryFn: () => api<SetOut[]>("/sets"),
  });
}

export function useSetDetail(ptcgSetId: string | undefined) {
  return useQuery({
    queryKey: ["sets", ptcgSetId],
    queryFn: () => api<SetDetailOut>(`/sets/${ptcgSetId}`),
    enabled: !!ptcgSetId,
  });
}

export function usePortfolio() {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api<PortfolioSummaryOut>("/collection/portfolio"),
  });
}

/** Upserts a collection_item and invalidates the set detail + portfolio queries that just
 * went stale, so owned/needed flags and portfolio value reflect the change immediately. */
export function useUpsertCollectionItem(ptcgSetId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CollectionItemIn) =>
      api<CollectionItemOut>("/collection/items", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      if (ptcgSetId) void queryClient.invalidateQueries({ queryKey: ["sets", ptcgSetId] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });
}
