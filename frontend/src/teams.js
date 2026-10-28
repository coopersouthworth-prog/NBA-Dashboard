// A readable-on-dark color for each team, used to fill its share of the
// prediction bar. Where a team's main color is too dark for a dark page,
// a lighter shade or its secondary color is used instead.
export const TEAM_COLORS = {
  ATL: "#E03A3E", BOS: "#1F9E57", BKN: "#A7A9AC", CHA: "#1D9CAB", CHI: "#CE1141",
  CLE: "#A6234F", DAL: "#1E7BD0", DEN: "#FEC524", DET: "#D6213A", GSW: "#FFC72C",
  HOU: "#D9254A", IND: "#FDBB30", LAC: "#D4223B", LAL: "#8551C2", MEM: "#6E89C2",
  MIA: "#C8234A", MIL: "#3C8B4C", MIN: "#3A86C8", NOP: "#B4975A", NYK: "#F58426",
  OKC: "#1F95DB", ORL: "#2A8FDB", PHI: "#2B7FD0", PHX: "#E56020", POR: "#E64A4E",
  SAC: "#8A5CC4", SAS: "#C4CED4", TOR: "#D61F45", UTA: "#8A6CCF", WAS: "#E31837",
};
const FALLBACK = "#7D8899";

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function tooSimilar(a, b) {
  const [r1, g1, b1] = hexToRgb(a);
  const [r2, g2, b2] = hexToRgb(b);
  return Math.hypot(r1 - r2, g1 - g2, b1 - b2) < 90;
}

/** Colors for a matchup. If both teams are (say) red, the home side goes neutral. */
export function matchupColors(awayTricode, homeTricode) {
  const away = TEAM_COLORS[awayTricode] || FALLBACK;
  let home = TEAM_COLORS[homeTricode] || FALLBACK;
  if (tooSimilar(away, home)) home = FALLBACK;
  return { away, home };
}
