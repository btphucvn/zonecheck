import type { ReactNode } from "react";
import { mv, val } from "../helpers";
import * as S from "../sections";
import { shareTable } from "./affluence";
import { Block, Facts, ShareRows, compareShares } from "./blocks";
import { flat, j, lad, metricMap, nextDoor, type TopicData, type TopicView } from "./topics";

// Demographics: ethnic makeup, religion, age, household types and background, one sub-tab each
// (/uk/<level>/<slug>/people, …/people/religion, …/age, …/households, …/background).
// Shares come from uk.share.* (derived from Census 2021) so each group has a national rank and a map.
// None of these figures feed a score, and nothing here ranks areas by ethnicity or religion.

export const PEOPLE_TABS = [
  { id: "ethnicity", label: "Ethnic makeup" },
  { id: "religion", label: "Religion" },
  { id: "age", label: "Age" },
  { id: "households", label: "Household type" },
  { id: "background", label: "Background" },
];

type G = { id: string; label: string };
const g = (k: string, label: string): G => ({ id: `uk.share.${k}`, label });

const ETHNIC: G[] = [
  g("eth_white_british", "White British"), g("eth_white_irish", "White Irish"), g("eth_other_white", "Other White"),
  g("eth_gypsy", "Gypsy or Irish Traveller"), g("eth_roma", "Roma"), g("eth_mixed", "Mixed"), g("eth_indian", "Indian"),
  g("eth_pakistani", "Pakistani"), g("eth_bangladeshi", "Bangladeshi"), g("eth_chinese", "Chinese"), g("eth_other_asian", "Other Asian"),
  g("eth_black_african", "Black African"), g("eth_black_caribbean", "Black Caribbean"), g("eth_other_black", "Other Black"),
  g("eth_arab", "Arab"), g("eth_other", "Other ethnic group"),
];
const RELIGION: G[] = [
  g("rel_none", "No religion"), g("rel_christian", "Christian"), g("rel_muslim", "Muslim"), g("rel_hindu", "Hindu"),
  g("rel_sikh", "Sikh"), g("rel_jewish", "Jewish"), g("rel_buddhist", "Buddhist"), g("rel_other", "Other religion"),
  g("rel_not_stated", "Not stated"),
];
const AGE: G[] = [g("age_under20", "Under 20"), g("age_20_39", "20 to 39"), g("age_40_59", "40 to 59"), g("age_60_79", "60 to 79"), g("age_80p", "80 and over")];
const HOUSEHOLDS: G[] = [
  g("hh_dependent_children", "Families with dependent children"), g("hh_couple_no_children", "Couples without children"),
  g("hh_adult_children", "Families with adult children at home"), g("hh_alone", "People living alone"),
  g("hh_aged_66p", "Families all aged 66+"), g("hh_shared", "Shared, multi-family or student"), g("hh_other_family", "Other family type"),
];

const pct = (x: number) => `${x < 10 ? x.toFixed(1) : Math.round(x)}%`;

/** Main group, and groups clearly above / below the regional average (as CrystalRoof words it). */
function profile(d: TopicData, groups: G[], noun: string) {
  const { r } = d.h;
  const region = r.ctx.region?.name ?? "the region";
  const rows = groups.map((x) => ({ ...x, here: val(r.metrics, x.id), avg: val(r.regionMetrics, x.id) }))
    .filter((x): x is G & { here: number; avg: number | null } => x.here != null);
  if (!rows.length) return null;
  const main = [...rows].sort((a, b) => b.here - a.here)[0];
  const diff = (x: { here: number; avg: number | null }) => x.avg != null && (Math.abs(x.here - x.avg) >= 3 && (x.here >= x.avg * 1.3 || x.here <= x.avg / 1.3));
  const higher = rows.filter((x) => diff(x) && x.here > x.avg!).sort((a, b) => b.here - b.avg! - (a.here - a.avg!));
  const lower = rows.filter((x) => diff(x) && x.here < x.avg!).sort((a, b) => a.here - a.avg! - (b.here - b.avg!));
  const line = (x: { label: string; here: number; avg: number | null }) => <li key={x.label}><b>{x.label}</b>: {pct(x.here)} ({region} average {pct(x.avg!)})</li>;
  return {
    main,
    verdict: `The largest ${noun} is ${main.label}, ${pct(main.here)} of ${noun === "household type" ? "households" : "residents"}`,
    body: (
      <>
        {higher.length > 0 && <><p className="tp-note">Higher than the {region} average:</p><ul className="tp-callouts">{higher.slice(0, 6).map(line)}</ul></>}
        {lower.length > 0 && <><p className="tp-note">Lower than the {region} average:</p><ul className="tp-callouts">{lower.slice(0, 6).map(line)}</ul></>}
        {!higher.length && !lower.length && <p className="tp-note">Every group is close to the {region} average.</p>}
      </>
    ),
  };
}

function groupTab(d: TopicData, o: { title: string; noun: string; groups: G[]; unit: string; table: string; dek: string; source: string; extra?: ReactNode }): TopicView {
  const { r } = d.h;
  const pr = profile(d, o.groups, o.noun);
  return {
    title: `${o.title} in ${d.name}`,
    description: `${o.title} of ${d.name} from Census 2021: every group, which are above or below the ${r.ctx.region?.name ?? "regional"} average, and a map by group.`,
    verdict: pr?.verdict ?? "",
    dek: o.dek,
    map: metricMap(d, o.groups.map((x) => ({ id: x.id, label: `${x.label} (%)`, fmt: "pct", dir: 0 }))),
    main: (
      <>
        {pr && <Block id="profile" title={`Main ${o.noun}`} note={`Compared with the average for ${r.ctx.region?.name ?? "the region"}.`}>{pr.body}</Block>}
        <Block id="table" title={o.table} note={`Share in each group, here and in ${r.ctx.region?.name ?? "the region"}.`}>
          {shareTable(d, o.groups, o.unit, "region")}
        </Block>
        {o.extra}
      </>
    ),
    side: pr ? <Facts items={[{ k: `Main ${o.noun}`, v: `${pr.main.label} ${pct(pr.main.here)}` },
      ...(lad(d) ? [{ k: `${pr.main.label} in ${lad(d)}`, v: val(d.h.r.ladMetrics, pr.main.id) != null ? pct(val(d.h.r.ladMetrics, pr.main.id)!) : null }] : [])]} /> : undefined,
    source: o.source,
  };
}

function background(d: TopicData): TopicView {
  const { r } = d.h;
  const cmp = (id: string, opts: Parameters<typeof compareShares>[2] = {}) => compareShares(j(r.metrics, id), j(r.ladMetrics, id), opts);
  const share = (title: string, id: string, rows: ReturnType<typeof cmp>, note: string, unit = "% of residents") => rows.length > 0 && (
    <Block id={id} title={title} note={note}><ShareRows rows={rows} other={lad(d) ?? "Local authority"} unit={unit} /></Block>
  );
  const owned = mv(r.metrics, "uk.share.owned");
  return {
    title: `Residents of ${d.name}`,
    description: `Background of residents of ${d.name}: tenure, work, country of birth, health and English language, from Census 2021.`,
    verdict: owned?.v != null ? `${pct(owned.v)} of households own their home` : "",
    dek: "Census 2021 describes the neighbourhood as a whole, not any one household.",
    map: metricMap(d, [
      { id: "uk.share.owned", label: "Owner-occupied homes (%)", fmt: "pct", dir: 0 },
      { id: "uk.share.private_rented", label: "Privately rented (%)", fmt: "pct", dir: 0 },
      { id: "uk.share.social_rented", label: "Socially rented (%)", fmt: "pct", dir: 0 },
    ]),
    main: (
      <>
        <Block id="tenure" title="Tenure" note={`Share of households, here and in ${lad(d) ?? "the local authority"}.`}>
          {shareTable(d, [g("owned", "Owned (incl. shared ownership)"), g("private_rented", "Private rented"), g("social_rented", "Social rented")], "% of households")}
        </Block>
        {flat(<S.People h={d.h} />)}
        {share("Work", "work", cmp("uk.census21.ts066", { top: 7 }), "Economic activity of residents aged 16+. Census 2021.")}
      </>
    ),
    side: (
      <>
        {share("Country of birth", "born", cmp("uk.census21.ts004", { top: 6 }), "Census 2021.")}
        {share("Health", "health", cmp("uk.census21.ts037"), "Self-reported general health. Census 2021.")}
        {share("English language", "lang", cmp("uk.census21.ts029", { top: 5 }), "Proficiency in English, residents aged 3+. Census 2021.")}
      </>
    ),
    after: nextDoor(d, (x) => `D${Math.round(x)}`, 1, "Deprivation decile, 10 = least deprived."),
    source: "Source: ONS Census 2021 (TS054, TS066, TS004, TS037, TS029).",
  };
}

const CENSUS = "Census 2021 counts everyone usually resident in the neighbourhood. None of these figures feed a score.";

export function people(d: TopicData): TopicView | null {
  switch (d.tab) {
    case null: case "ethnicity":
      return groupTab(d, { title: "Ethnic makeup", noun: "ethnic group", groups: ETHNIC, unit: "% of residents", table: "Ethnic groups", dek: CENSUS, source: "Source: ONS Census 2021, table TS021." });
    case "religion":
      return groupTab(d, { title: "Religion", noun: "religion", groups: RELIGION, unit: "% of residents", table: "Religion", dek: `${CENSUS} The religion question was voluntary.`, source: "Source: ONS Census 2021, table TS030." });
    case "age":
      return groupTab(d, { title: "Age of residents", noun: "age band", groups: AGE, unit: "% of residents", table: "Age bands", dek: CENSUS, source: "Source: ONS Census 2021, table TS007A." });
    case "households":
      return groupTab(d, { title: "Household types", noun: "household type", groups: HOUSEHOLDS, unit: "% of households", table: "Household types", dek: "Census 2021 household composition. Dependent children are aged under 16, or 16 to 18 in full-time education.", source: "Source: ONS Census 2021, table TS003." });
    case "background": return background(d);
    default: return null;
  }
}
