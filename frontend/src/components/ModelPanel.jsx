import { pct } from "../format.js";

// Live head-to-head with the betting market: the toughest benchmark in sports
// forecasting, because prices reflect the money of thousands of bettors.
function MarketComparison({ vs }) {
  if (!vs || vs.games === 0) return null;
  const better = vs.model_log_loss < vs.market_log_loss;
  return (
    <div className="vs-market">
      <h3>Against the betting market this season</h3>
      <p>
        Before each game, the market’s win probability is taken from sportsbook odds (with the
        bookmakers’ margin removed) and saved next to the model’s. Across {vs.games} finished games:
      </p>
      <dl className="compare">
        {[
          { label: "Betting market", value: vs.market_accuracy },
          { label: "This model", value: vs.model_accuracy, ours: true },
        ].map((r) => (
          <div key={r.label} className={r.ours ? "compare-row ours" : "compare-row"}>
            <dt>{r.label}</dt>
            <dd>
              <span className="compare-track"><span className="compare-fill" style={{ "--share": r.value }} /></span>
              <span className="compare-value">{pct(r.value, 1)}</span>
            </dd>
          </div>
        ))}
      </dl>
      <p>
        Log loss, which judges the probabilities themselves (lower is better), is{" "}
        <strong>{vs.model_log_loss.toFixed(3)}</strong> for the model and{" "}
        <strong>{vs.market_log_loss.toFixed(3)}</strong> for the market
        {better ? ", so the model’s probabilities have been sharper so far." : "."}
        {vs.disagreements > 0 && (
          <> They picked different winners in {vs.disagreements} game{vs.disagreements === 1 ? "" : "s"}, and
          the model was right in {vs.model_won_disagreements}.</>
        )}
      </p>
      <p className="muted small">
        The marker on each game’s bar shows where the market’s probability sits.
      </p>
    </div>
  );
}

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
      <MarketComparison vs={model.vs_market} />
      <p className="muted small">Predictions lock before each game starts and are never changed afterward.</p>
    </section>
  );
}
