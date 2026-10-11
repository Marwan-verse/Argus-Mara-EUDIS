import { vesselName } from "./live-format.mjs";

const collator = new Intl.Collator("en-GB");
export const searchKey = (value) => value.trim().toLocaleLowerCase("en-GB");

// Build name order and search strings only when observations change.
export function indexDirectory(vessels) {
  return vessels
    .map((vessel) => ({
      vessel,
      name: vesselName(vessel),
      search: searchKey(`${vessel.name} ${vessel.mmsi}`),
    }))
    .sort(
      (a, b) =>
        collator.compare(a.name, b.name) ||
        collator.compare(a.vessel.mmsi, b.vessel.mmsi),
    );
}

export function filterDirectory(directory, query) {
  return query
    ? directory.filter((entry) => entry.search.includes(query))
    : directory;
}
