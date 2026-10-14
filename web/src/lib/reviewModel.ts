// Shared between the review form (client) and the API route: aspects, tags and validation.

export const ASPECTS = [
  ["architecture", "Local architecture and beauty"], ["green", "Green spaces"], ["prosperity", "Prosperity"], ["safety", "Safety"],
  ["high_street", "High street and shops"], ["transport", "Transport links"], ["community", "Local community"], ["schools", "Schools"],
] as const;
export type Aspect = (typeof ASPECTS)[number][0];

export const TAGS = ["Urban", "Suburban", "Rural", "Residential", "Lively", "Peaceful", "Diverse", "Family-friendly", "Student area",
  "Up and coming", "Leafy", "Historic", "New builds", "Busy roads", "Nightlife"] as const;

export const RELATIONS = [["resident", "I live here now"], ["former", "I used to live here"], ["worker", "I work here"]] as const;

export interface ReviewInput {
  postcode: string; ratings: Partial<Record<Aspect, number | null>>; tags: string[]; title: string; body: string; improve: string;
  author: string; relation: string; years: string; website?: string; startedAt?: number;
}

/** Returns an error message, or null when the review is acceptable. */
export function validateReview(x: ReviewInput): string | null {
  if (!/^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$/.test(x.postcode)) return "Enter the full postcode of the street you are reviewing.";
  const scores = ASPECTS.map(([k]) => x.ratings[k]).filter((v): v is number => typeof v === "number");
  if (scores.length < 5) return "Rate at least five of the eight aspects.";
  if (scores.some((v) => !Number.isInteger(v) || v < 1 || v > 10)) return "Ratings run from 1 to 10.";
  if (x.title.trim().length < 5 || x.title.length > 120) return "Give your review a short title (5 to 120 characters).";
  if (x.body.trim().length < 80 || x.body.length > 4000) return "Write at least 80 characters about the area (4,000 at most).";
  if (x.improve.length > 2000) return "Keep \"things to improve\" under 2,000 characters.";
  if (x.author.trim().length < 2 || x.author.length > 40) return "Add a display name (2 to 40 characters).";
  if (!RELATIONS.some(([k]) => k === x.relation)) return "Tell us how you know the area.";
  if (x.tags.length > 6 || x.tags.some((t) => !(TAGS as readonly string[]).includes(t))) return "Choose up to six tags from the list.";
  if (/https?:\/\/|www\./i.test(`${x.title} ${x.body} ${x.improve}`)) return "Please leave out links.";
  return null;
}
