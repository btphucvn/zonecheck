"use client";

export function ThemeToggle({ label }: { label: string }) {
  const flip = () => {
    const r = document.documentElement;
    const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    r.dataset.theme = next;
    try { localStorage.setItem("zc:theme", next); } catch { /* ignore */ }
    window.dispatchEvent(new Event("zc:theme"));
  };
  return <button type="button" className="theme-btn" onClick={flip}>{label}</button>;
}
