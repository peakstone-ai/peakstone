"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

/** A URL-driven <select>: changing it rewrites one query param and navigates, preserving the rest
 * of the active filters. Server components read the new searchParams and re-render. */
export function SelectFilter({
  param,
  label,
  options,
  allLabel = "All",
}: {
  param: string;
  label: string;
  options: string[];
  allLabel?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const value = sp.get(param) ?? "";

  function onChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const next = new URLSearchParams(sp.toString());
    if (e.target.value) next.set(param, e.target.value);
    else next.delete(param);
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  }

  return (
    <label className="flex items-center gap-1.5 text-sm text-stone-500">
      {label}:
      <select
        value={value}
        onChange={onChange}
        className="rounded-md border border-stone-700 bg-stone-900 px-2 py-1 text-sm text-stone-200"
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o.replace(/[-_]/g, " ")}
          </option>
        ))}
      </select>
    </label>
  );
}
