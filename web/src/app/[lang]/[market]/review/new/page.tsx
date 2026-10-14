import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ReviewForm } from "@/components/review/ReviewForm";

type Props = PageProps<"/[lang]/[market]/review/new">;

export const metadata: Metadata = {
  title: "Review your neighbourhood",
  description: "Tell home movers what it is really like to live in your area. Reviews are checked before they appear.",
  alternates: { canonical: "/uk/review/new" },
};

export async function generateStaticParams() {
  return [{ market: "uk" }];
}

export default function NewReviewPage(props: Props) {
  return (
    <main className="wrap">
      <div className="page-head">
        <h1>Review your neighbourhood</h1>
        <p>Official data says a lot about an area, but not what it feels like. Help people moving in by describing your street and neighbourhood.</p>
      </div>
      <Suspense fallback={<div className="skeleton" style={{ minHeight: 400 }} />}>
        <Body {...props} />
      </Suspense>
    </main>
  );
}

async function Body({ params, searchParams }: Props) {
  const { market } = await params;
  if (market !== "uk") notFound();
  const sp = await searchParams;
  const postcode = typeof sp.postcode === "string" ? sp.postcode.toUpperCase() : "";
  return <ReviewForm postcode={postcode} />;
}
