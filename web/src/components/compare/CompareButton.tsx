"use client";

import { useState } from "react";
import { itemKey, useApp, type CompareItem } from "../Providers";

export function CompareButton({ item, labels, variant = "btn" }: {
  item: CompareItem;
  labels: { add: string; added: string; max: string };
  variant?: "btn" | "link";
}) {
  const { compare, toggleCompare } = useApp();
  const [full, setFull] = useState(false);
  const on = compare.some((c) => itemKey(c) === itemKey(item));
  const click = () => setFull(!toggleCompare(item));
  return (
    <>
      <button type="button" className={variant === "btn" ? "btn" : "linkish"} aria-pressed={on} onClick={click}>
        {on ? labels.added : labels.add}
      </button>
      {full && <span role="status" className="m-src">{labels.max}</span>}
    </>
  );
}
