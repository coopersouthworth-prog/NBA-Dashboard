import TeamLogo from "./TeamLogo.jsx";
import { formatTipoff, pct } from "../format.js";
import { matchupColors } from "../teams.js";

function Side({ team, side, status, isWinner }) {
  const showScore = status !== "scheduled" && team.score !== null;
  const dim = status === "final" && !isWinner;
  return (
    <div className={`side side-${side}${dim ? " side-lost" : ""}`}>
      <TeamLogo url={team.logo_url} />
      <div className="team-text">
        <span className="tricode">{team.tricode}</span>
        <span className="team-name">{team.name}</span>
      </div>
      {showScore && <span className="score">{team.score}</span>}
    </div>
  );
}

function Status({ game }) {
  if (game.status === "live") {
    return <span className="status status-live"><span className="live-dot" aria-hidden="true" />{game.status_text}</span>;
  }
  if (game.status === "final") return <span className="status">{game.status_text || "Final"}</span>;
  return <span className="status">{formatTipoff(game.start_time_utc) || game.status_text}</span>;
}

function Result({ prediction }) {
  if (!prediction || prediction.correct === null || prediction.correct === undefined) return <span className="result" />;
  return prediction.correct
    ? <span className="result result-hit" title="The model picked the winner">✓ Pick</span>
    : <span className="result result-miss" title="The model picked the loser">✗ Pick</span>;
}

function ProbabilityBar({ game }) {
  const p = game.prediction;
  if (!p) return <div className="bar-wrap bar-none">No prediction for this game</div>;

  const colors = matchupColors(game.away.tricode, game.home.tricode);
  const awayFav = p.away_win_prob > p.home_win_prob;
  const winner = awayFav ? game.away : game.home;
  return (
    <div
      className="bar-wrap"
      role="img"
      aria-label={`Model gives ${winner.name} a ${pct(p.winner_prob)} chance to win`}
    >
      <div className="bar-labels" aria-hidden="true">
        <span className={awayFav ? "fav" : ""}>{pct(p.away_win_prob)}</span>
        <span className={!awayFav ? "fav" : ""}>{pct(p.home_win_prob)}</span>
      </div>
      <div className="bar-track" aria-hidden="true">
        <span className="bar-fill" style={{ "--share": p.away_win_prob, background: colors.away }} />
        <span className="bar-fill" style={{ "--share": p.home_win_prob, background: colors.home }} />
      </div>
    </div>
  );
}

export default function GameRow({ game }) {
  const final = game.status === "final";
  const homeWon = final && game.home.score > game.away.score;
  return (
    <li className={`game game-${game.status}`}>
      <Status game={game} />
      <Side team={game.away} side="away" status={game.status} isWinner={final && !homeWon} />
      <ProbabilityBar game={game} />
      <Side team={game.home} side="home" status={game.status} isWinner={homeWon} />
      <Result prediction={game.prediction} />
    </li>
  );
}
