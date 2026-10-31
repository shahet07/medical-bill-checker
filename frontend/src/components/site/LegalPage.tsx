import { PlainChrome } from "./SiteChrome";

/** A policy page. `draft` shows a notice that the text has not had legal review yet. */
export default function LegalPage(props: { title: string; updated: string; draft?: boolean; children: React.ReactNode }) {
  return (
    <div className="site">
      <PlainChrome>
        <main className="site-wrap narrow legal">
          <h1>{props.title}</h1>
          <p className="muted">Last updated {props.updated}</p>
          {props.draft && (
            <p className="note" role="note">
              Draft. This text describes how the software works and has not yet been reviewed by a lawyer. Text in
              [brackets] is filled in by whoever runs this service.
            </p>
          )}
          <p className="muted" lang="es">
            Esta página está disponible solo en inglés por ahora.
          </p>
          {props.children}
        </main>
      </PlainChrome>
    </div>
  );
}
