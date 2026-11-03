import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api, type Page } from "./api";
import { useOrgKey } from "./session";

/** Cursor pagination with IntersectionObserver-driven loading of the next page. */
export function useCursorList<T>(key: string, path: string, params: Record<string, string | undefined> = {}, opts: { pollWhile?: (items: T[]) => boolean; pollMs?: number } = {}) {
  const org = useOrgKey();
  const q = useInfiniteQuery({
    queryKey: [org, key, params],
    queryFn: ({ pageParam, signal }) => api<Page<T>>(path, { params: { ...params, limit: 20, cursor: pageParam }, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    // Poll only while the caller says work is actually in flight (e.g. documents still processing).
    refetchInterval: (query) => (opts.pollWhile?.(query.state.data?.pages.flatMap((p) => p.items) ?? []) ? opts.pollMs ?? 2000 : false),
  });
  const sentinel = useRef<HTMLDivElement | null>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = q;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasNextPage) return;
    const io = new IntersectionObserver((e) => { if (e[0].isIntersecting && !isFetchingNextPage) void fetchNextPage(); }, { rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  return { ...q, items: q.data?.pages.flatMap((p) => p.items) ?? [], sentinel };
}
