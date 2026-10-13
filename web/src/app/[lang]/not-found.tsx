import Link from "next/link";

export default function NotFound() {
  return (
    <main className="wrap" style={{ padding: "60px 16px" }}>
      <div className="plate">404<small>Not on the map</small></div>
      <h1 style={{ marginTop: 16 }}>We couldn&apos;t find that area</h1>
      <p>Check the postcode or place name and search again, or <Link href="/">go to the home page</Link>.</p>
    </main>
  );
}
