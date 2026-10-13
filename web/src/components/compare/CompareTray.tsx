"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { itemKey, useApp } from "../Providers";

export function compareHref(items: { level: string; slug: string }[]): string {
  const p = new URLSearchParams();
  items.forEach((i, n) => p.set("abcd"[n], `${i.level}:${i.slug}`));
  return `/uk/compare?${p.toString()}`;
}

export function CompareTray({ label, removeLabel }: { label: string; removeLabel: string }) {
  const { compare, removeCompare } = useApp();
  const path = usePathname();
  const show = compare.length > 0 && !path.includes("/compare");
  return (
    <div className={`tray${show ? " show" : ""}`} role="region" aria-label="Compare tray" aria-hidden={!show} inert={!show}>
      <span className="pills">
        {compare.map((c) => (
          <span className="pill" key={itemKey(c)}>
            {c.label}
            <button type="button" aria-label={removeLabel.replace("{name}", c.label)} onClick={() => removeCompare(itemKey(c))}>×</button>
          </span>
        ))}
      </span>
      <Link href={compareHref(compare)} prefetch={false}>{label}</Link>
    </div>
  );
}

export function CompareCount() {
  const { compare } = useApp();
  return <span className="cmp-count num" aria-label={`${compare.length} areas in compare`}>{compare.length}</span>;
}

export function CompareNavLink({ label }: { label: string }) {
  const { compare } = useApp();
  return (
    <Link href={compare.length ? compareHref(compare) : "/uk/compare"} prefetch={false}>
      {label}
      <CompareCount />
    </Link>
  );
}
