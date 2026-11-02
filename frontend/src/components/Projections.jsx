import { useEffect, useState } from "react";
import { fetchProjections } from "../api.js";
import { formatClock, formatGameDay } from "../format.js";
import TeamLogo from "./TeamLogo.jsx";

// Show odds the way people read them: "<1%" and ">99%" instead of 0% / 100%
// for outcomes that are unlikely but still possible.
function odds(p) {
  if (p === 0) return "–";
  if (p < 0.005) return "<1%";
  if (p > 0.995 && p < 1) return ">99%";
  return `${Math.round(p * 100)}%`;
}

function Conference({ name, teams }) {
  return (
    <section className="conf" aria-labelledby={`conf-${name}`}>
      <h2 id={`conf-${name}`}>{name}ern Conference</h2>
      <div className="table-scroll">
        <table className="proj">
          <thead>
            <tr>
              <th scope="col" className="col-rank"><span className="sr-only">Projected rank</span></th>
              <th scope="col" className="col-team">Team</th>
              <th scope="col" className="num">Record</th>
              <th scope="col" className="num">Projected</th>
              <th scope="col" className="col-bar">Make playoffs</th>
              <th scope="col" className="num col-hide">Conf. final</th>
              <th scope="col" className="num col-hide">Finals</th>
              <th scope="col" className="num">Title</th>
            </tr>
          </thead>
          <tbody>
            {teams.map((t, i) => (
              <tr key={t.team_id} className={i === 6 ? "cut-playin" : i === 10 ? "cut-out" : ""}>
                <td className="col-rank">{i + 1}</td>
                <th scope="row" className="col-team">
                  <span className="proj-team">
                    <TeamLogo url={t.logo_url} size={24} />
                    <span className="tricode">{t.tricode}</span>
                    <span className="team-name">{t.name}</span>
                  </span>
                </th>
                <td className="num">{t.wins}–{t.losses}</td>
                <td className="num strong">{Math.round(t.proj_wins)}–{Math.round(t.proj_losses)}</td>
                <td className="col-bar">
                  <span className="odds-bar" aria-hidden="true">
                    <span className="odds-fill" style={{ "--share": t.p_playoffs }} />
                  </span>
                  <span className="odds-value">{odds(t.p_playoffs)}</span>
                </td>
                <td className="num col-hide">{odds(t.p_conf_finals)}</td>
                <td className="num col-hide">{odds(t.p_finals)}</td>
                <td className="num strong">{odds(t.p_title)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function Projections() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetchProjections().then(setData).catch(() => setError(true));
  }, []);

  if (error) return <p className="notice notice-error" role="alert">Couldn’t load the playoff odds. Try refreshing in a minute.</p>;
  if (!data) return <p className="notice" role="status">Loading playoff odds…</p>;
  if (!data.east.length) return <p className="notice">The first simulation hasn’t run yet. It runs each morning with the day’s predictions.</p>;

  const when = data.simulated_at;
  return (
    <div className="projections">
      <p className="proj-meta">
        Based on {data.sims?.toLocaleString()} simulations of the {data.games_left?.toLocaleString()} regular-season
        games left, updated {formatGameDay(when?.slice(0, 10))} at {formatClock(when)}.
        Teams above the first line finish top six and go straight to the playoffs; seeds 7 through 10 play
        in the play-in tournament.
      </p>
      <div className="conf-grid">
        <Conference name="East" teams={data.east} />
        <Conference name="West" teams={data.west} />
      </div>
      <section className="method" aria-labelledby="method-title">
        <h2 id="method-title">How the simulation works</h2>
        <p>
          Every remaining game is played out using the model’s win probability for that matchup, including each
          team’s real rest days from the schedule. Then each conference is seeded, the play-in tournament decides
          the 7th and 8th seeds, and the playoffs are played as best-of-seven series with home court for the
          higher seed.
        </p>
        <p>
          Each simulated season also gives every team a small random boost or penalty to its strength, because
          a team’s current numbers are only an estimate of how good it really is. That uncertainty is largest
          early in the season and shrinks as games are played. Ties in the standings are broken at random.
        </p>
      </section>
    </div>
  );
}
