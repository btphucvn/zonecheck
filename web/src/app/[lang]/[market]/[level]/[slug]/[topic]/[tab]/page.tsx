import type { Metadata } from "next";
import { TopicPage, topicMetadata } from "@/components/report/topic/TopicPage";

type Props = PageProps<"/[lang]/[market]/[level]/[slug]/[topic]/[tab]">;

// Sub-tab of a topic page, e.g. /uk/sector/se15-4/affluence/deprivation.
export async function generateStaticParams() {
  return [{ market: "uk", level: "sector", slug: "se15-4", topic: "affluence", tab: "deprivation" }];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return topicMetadata(params);
}

export default function Page({ params }: Props) {
  return <TopicPage params={params} />;
}
