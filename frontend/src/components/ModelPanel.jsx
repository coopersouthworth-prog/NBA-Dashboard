import { pct } from "../format.js";

// Compares the model against two simple strategies, drawn as the same kind of
// bar used for each game, so the page has one consistent visual language.
export default function ModelPanel({ model }) {
  if (!model?.test_accuracy) return null;
  const rows = [
    { label: "Always pick the home team", value: model.baseline_home_accuracy },
    { label: "Pick the team with the higher Elo rating", value: model.baseline_elo_accuracy },
    { label: "This model", value: model.test_accuracy, ours: true },
  ];
  return (
    <section className="model" aria-labelledby="model-title">
      <h2 id="model-title">How the picks are made</h2>
      <p>
        Each morning, a {model.model?.toLowerCase() || "machine learning"} model estimates every
        game’s win probability from what’s known before tip-off: team strength (Elo ratings),
        scoring efficiency over the last 10 games, season record, rest, and back-to-backs.
      </p>
      <p>
        It was tested on all {model.test_games?.toLocaleString()} games of the {model.test_season} season,
        which it never saw during training.
      </p>
      <dl className="compare">
        {rows.map((r) => (
          <div key={r.label} className={r.ours ? "compare-row ours" : "compare-row"}>
            <dt>{r.label}</dt>
            <dd>
              <span className="compare-track"><span className="compare-fill" style={{ "--share": r.value ?? 0 }} /></span>
              <span className="compare-value">{pct(r.value, 1)}</span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="muted small">Predictions lock before each game starts and are never changed afterward.</p>
    </section>
  );
}
