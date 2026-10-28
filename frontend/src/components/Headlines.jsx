import { timeAgo } from "../format.js";

export default function Headlines({ headlines }) {
  return (
    <section className="headlines" aria-labelledby="headlines-title">
      <h2 id="headlines-title">Headlines</h2>
      {headlines.length === 0 ? (
        <p className="muted">No headlines yet. They refresh every few hours.</p>
      ) : (
        <ul>
          {headlines.map((h) => (
            <li key={h.link}>
              <a href={h.link} target="_blank" rel="noopener noreferrer">{h.title}</a>
              <span className="headline-meta">
                {h.source}
                {h.published_at && <time dateTime={h.published_at}>{timeAgo(h.published_at)}</time>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
