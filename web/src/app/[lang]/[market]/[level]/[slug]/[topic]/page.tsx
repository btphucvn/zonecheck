import type { Metadata } from "next";
import { TopicPage, topicMetadata } from "@/components/report/topic/TopicPage";

type Props = PageProps<"/[lang]/[market]/[level]/[slug]/[topic]">;

// Detail page for one report section, e.g. /uk/postcode/se15-4dx/crime (first sub-tab when the topic has tabs).
// Rendered on first visit and cached like the report itself.
export async function generateStaticParams() {
  return [{ market: "uk", level: "sector", slug: "se15-4", topic: "crime" }];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return topicMetadata(params);
}

export default function Page({ params }: Props) {
  return <TopicPage params={params} />;
}
