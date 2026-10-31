import { at } from "@/lib/base";
import { PlainChrome, SOURCE_URL } from "./SiteChrome";

/** Shown on the website-only build (GitHub Pages) where the app needs its server. */
export default function NotHosted(props: { what: "app" | "verify" }) {
  return (
    <div className="site">
      <PlainChrome>
        <main className="site-wrap narrow legal">
          <h1>{props.what === "app" ? "The bill checker isn't online yet" : "Letter verification isn't online yet"}</h1>
          <p className="lead">
            This is the Clyvexa website. {props.what === "app" ? "Checking a bill" : "Verifying a letter"} needs the Clyvexa
            server, which isn&rsquo;t hosted on this address yet.
          </p>
          <p lang="es" className="muted">
            Este es el sitio web de Clyvexa. {props.what === "app" ? "Revisar una factura" : "Verificar una carta"} necesita el
            servidor de Clyvexa, que todavía no está disponible en esta dirección.
          </p>
          <p>
            Clyvexa is open source: you can run the full app yourself by following the instructions in the{" "}
            <a href={SOURCE_URL + "#readme"} rel="noopener">
              project&rsquo;s README
            </a>
            .
          </p>
          <p>
            <a href={at("/")} className="circle-link">
              Back to the website <span aria-hidden="true">→</span>
            </a>
          </p>
        </main>
      </PlainChrome>
    </div>
  );
}
