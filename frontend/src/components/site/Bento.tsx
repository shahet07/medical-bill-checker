import type { SiteText } from "@/lib/siteText";
import Icon from "./Icon";

// Feature cards, each with a small live-looking piece of the app instead of an icon.
export default function Bento({ s }: { s: SiteText }) {
  const b = s.bento;
  return (
    <ul className="bento reveal stagger">
      <li className="card-b wide">
        <div className="wide-copy">
          <h3>{b.checks.title}</h3>
          <p>{b.checks.body}</p>
        </div>
        <div className="chips checks-chips">
          {s.checks.items.map((c, i) => (
            <span key={c.title} className={"chip" + (i === 0 || i === 1 ? " warn" : "")}>
              {c.title}
            </span>
          ))}
        </div>
      </li>

      <li className="card-b">
        <h3>{b.compare.title}</h3>
        <p>{b.compare.body}</p>
        <div className="compare">
          <div>
            <span>{b.compare.bill}</span>
            <strong className="warn">{s.mock.bill.due}</strong>
          </div>
          <span className="neq" aria-hidden="true">
            ≠
          </span>
          <div>
            <span>{b.compare.eob}</span>
            <strong className="ok">$96.40</strong>
          </div>
        </div>
      </li>

      <li className="card-b">
        <h3>{b.letters.title}</h3>
        <p>{b.letters.body}</p>
        <div className="verify-mini">
          <svg viewBox="0 0 21 21" className="qr" aria-hidden="true">
            {QR.map(([x, y]) => (
              <rect key={x + "-" + y} x={x} y={y} width="1" height="1" />
            ))}
          </svg>
          <span className="verified">
            <Icon name="lock" /> {b.letters.verified}
          </span>
        </div>
      </li>

      <li className="card-b">
        <h3>{b.photo.title}</h3>
        <p>{b.photo.body}</p>
        <div className="phone-mini" aria-hidden="true">
          <div className="phone-shot blur" />
          <div className="phone-pills">
            <span className="pill warn">{b.photo.blurry}</span>
            <span className="pill ok">✓ {b.photo.clear}</span>
          </div>
        </div>
      </li>

      <li className="card-b">
        <h3>{b.refund.title}</h3>
        <p>{b.refund.body}</p>
        <div className="refund-mini">
          <strong>{b.refund.amount}</strong>
          <span>{b.refund.found}</span>
          <div className="bars" aria-hidden="true">
            <i />
            <i />
            <i />
            <i className="hot" />
            <i />
          </div>
        </div>
      </li>

      <li className="card-b wide">
        <div className="wide-copy">
          <h3>{b.rehearse.title}</h3>
          <p>{b.rehearse.body}</p>
          <div className="chips">
            {b.rehearse.tips.map((t) => (
              <span key={t} className="chip ok">
                ✓ {t}
              </span>
            ))}
          </div>
        </div>
        <div className="chat-mini" aria-hidden="true">
          <div className="bubble rep">
            <small>{b.rehearse.rep}</small>
            {b.rehearse.repLine}
          </div>
          <div className="bubble you">
            <small>{b.rehearse.you}</small>
            {b.rehearse.youLine}
          </div>
          <div className="bubble rep typing">
            <i />
            <i />
            <i />
          </div>
        </div>
      </li>

      <li className="card-b">
        <h3>{b.radar.title}</h3>
        <p>{b.radar.body}</p>
        <ul className="radar-mini" aria-hidden="true">
          {b.radar.rows.map((r, i) => (
            <li key={r}>
              <span className="pulse-dot" aria-hidden="true" />
              {r}
              <b>
                {[14, 11, 10][i]} {b.radar.reports}
              </b>
            </li>
          ))}
        </ul>
        <p className="tiny">{b.radar.note}</p>
      </li>
    </ul>
  );
}

// A decorative QR-like pattern (finder squares plus a fixed scatter), not a real code.
const QR: [number, number][] = (() => {
  const cells: [number, number][] = [];
  const finder = (ox: number, oy: number) => {
    for (let y = 0; y < 7; y++)
      for (let x = 0; x < 7; x++)
        if (x === 0 || y === 0 || x === 6 || y === 6 || (x >= 2 && x <= 4 && y >= 2 && y <= 4)) cells.push([ox + x, oy + y]);
  };
  finder(0, 0);
  finder(14, 0);
  finder(0, 14);
  let seed = 7;
  for (let y = 0; y < 21; y++)
    for (let x = 0; x < 21; x++) {
      if ((x < 8 && y < 8) || (x > 12 && y < 8) || (x < 8 && y > 12)) continue;
      seed = (seed * 9301 + 49297) % 233280;
      if (seed / 233280 < 0.45) cells.push([x, y]);
    }
  return cells;
})();
