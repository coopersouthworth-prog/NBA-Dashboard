import { useCallback, useEffect, useState } from "react";
import { fetchGames, fetchHeadlines, fetchModel } from "./api.js";
import { formatClock, formatGameDay, pct } from "./format.js";
import GameRow from "./components/GameRow.jsx";
import Headlines from "./components/Headlines.jsx";
import ModelPanel from "./components/ModelPanel.jsx";

const GAMES_REFRESH_MS = 60_000;        // scores
const SLOW_REFRESH_MS = 10 * 60_000;    // headlines + model record
const RETRY_MS = 30_000;

function useSlowStartNotice(active) {
  // The free server sleeps when idle and can take up to a minute to wake.
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!active) return undefined;
    const t = setTimeout(() => setSlow(true), 4000);
    return () => clearTimeout(t);
  }, [active]);
  return active && slow;
}

export default function App() {
  const [games, setGames] = useState(null);
  const [headlines, setHeadlines] = useState([]);
  const [model, setModel] = useState(null);
  const [error, setError] = useState(null);

  const loadGames = useCallback(async () => {
    try {
      setGames(await fetchGames());
      setError(null);
    } catch {
      setError("The game data server isn’t responding. Trying again in 30 seconds.");
    }
  }, []);

  const loadSlow = useCallback(async () => {
    const [h, m] = await Promise.allSettled([fetchHeadlines(), fetchModel()]);
    if (h.status === "fulfilled") setHeadlines(h.value);
    if (m.status === "fulfilled") setModel(m.value);
  }, []);

  useEffect(() => {
    loadGames();
    loadSlow();
    const slowTimer = setInterval(loadSlow, SLOW_REFRESH_MS);
    return () => clearInterval(slowTimer);
  }, [loadGames, loadSlow]);

  useEffect(() => {
    const t = setInterval(loadGames, error ? RETRY_MS : GAMES_REFRESH_MS);
    return () => clearInterval(t);
  }, [loadGames, error]);

  const loading = games === null && !error;
  const slow = useSlowStartNotice(loading);
  const record = model?.season_record;
  const list = games?.games ?? [];

  return (
    <div className="page">
      <header className="masthead">
        <div className="brand">
          <img src="/favicon.svg" width="22" height="22" alt="" />
          <span>Tip-Off</span>
        </div>
        <div className="masthead-main">
          <h1>{formatGameDay(games?.date)}</h1>
          {games && (
            <p className="masthead-sub">
              {list.length === 0 ? "No games scheduled." : `${list.length} games, with the model’s pick for each.`}
              {games.updated_at && <span className="updated"> Updated {formatClock(games.updated_at)}.</span>}
            </p>
          )}
        </div>
        {record && record.games > 0 && (
          <div className="record" aria-label={`Model record this season: ${record.correct} correct out of ${record.games}`}>
            <span className="record-value">{record.correct}–{record.games - record.correct}</span>
            <span className="record-label">Model’s record this season, {pct(record.accuracy)} correct</span>
          </div>
        )}
      </header>

      <div className="layout">
        <main>
          {error && <p className="notice notice-error" role="alert">{error}</p>}
          {loading && (
            <p className="notice" role="status">
              {slow ? "Waking up the server. This can take up to a minute on the first visit." : "Loading today’s games…"}
            </p>
          )}
          {games && list.length === 0 && (
            <p className="notice">No NBA games today. Check back tomorrow for the next slate and predictions.</p>
          )}
          {list.length > 0 && (
            <ol className="games" aria-label="Today’s games">
              {list.map((g) => <GameRow key={g.game_id} game={g} />)}
            </ol>
          )}
          <ModelPanel model={model} />
        </main>
        <aside>
          <Headlines headlines={headlines} />
        </aside>
      </div>

      <footer className="footer">
        <p>Game data from NBA.com. Headlines from ESPN. Predictions are for fun, not betting advice.</p>
      </footer>
    </div>
  );
}
