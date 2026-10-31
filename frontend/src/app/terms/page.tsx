import type { Metadata } from "next";
import LegalPage from "@/components/site/LegalPage";
import { at } from "@/lib/base";

export const metadata: Metadata = { title: "Terms of use · Clyvexa" };

export default function Terms() {
  return (
    <LegalPage title="Terms of use" updated="October 31, 2026" draft>
      <p>
        These terms apply to the Clyvexa service run by [operator name]. By creating an account you agree to them.
        Contact: [contact email].
      </p>

      <h2>What Clyvexa does</h2>
      <p>
        Clyvexa reads medical bills and insurance statements you upload, points out things that may be worth checking,
        explains them, and drafts letters and call notes for you to use. It is an information tool.
      </p>

      <h2>What Clyvexa is not</h2>
      <ul>
        <li>
          It is not legal, medical, financial or insurance advice, and it is not a law firm, a medical provider or an
          insurer.
        </li>
        <li>
          It can be wrong. Reading documents with AI can make mistakes, and a check that finds nothing is not a guarantee
          that a bill is correct. Review what it read and its results before you rely on them.
        </li>
        <li>
          It does not contact your provider or insurer, and it does not negotiate or pay bills for you. You decide what
          to send.
        </li>
        <li>Don&rsquo;t ignore a bill or a deadline because of a result. Keep paying attention to due dates.</li>
      </ul>

      <h2>Your account and your content</h2>
      <ul>
        <li>You must be 18 or older and give a working email address.</li>
        <li>Keep your password private. You are responsible for activity on your account.</li>
        <li>
          Upload only documents you have the right to use, such as your own bills or those of someone you are authorized
          to help.
        </li>
        <li>
          Your documents stay yours. You let us process them only to provide the service, as the{" "}
          <a href={at("/privacy")}>privacy policy</a> describes.
        </li>
      </ul>

      <h2>Acceptable use</h2>
      <p>
        Don&rsquo;t misuse the service: no attempts to access other people&rsquo;s data, overload or disrupt the service,
        or use it to create false documents. We may suspend accounts that do.
      </p>

      <h2>Open source</h2>
      <p>
        The Clyvexa software is open source under the MIT License. These terms cover the hosted service, not your use
        of the source code, which the license covers.
      </p>

      <h2>No warranty and limits on liability</h2>
      <p>
        The service is provided &ldquo;as is&rdquo; and &ldquo;as available&rdquo;, without warranties of any kind, to
        the extent the law allows. [Limitation of liability, governing law and dispute terms to be added after legal
        review.]
      </p>

      <h2>Ending your use</h2>
      <p>
        You can stop at any time and <a href={at("/delete-account")}>delete your account</a>. We may change or stop the
        service; if we stop it, we will give notice so you can save your letters first.
      </p>

      <h2>Changes</h2>
      <p>If we change these terms in a way that matters, we will say so here and in the app before they apply.</p>
    </LegalPage>
  );
}
