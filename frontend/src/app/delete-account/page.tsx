import type { Metadata } from "next";
import LegalPage from "@/components/site/LegalPage";
import { at } from "@/lib/base";

export const metadata: Metadata = { title: "Delete your account · Clyvexa" };

export default function DeleteAccount() {
  return (
    <LegalPage title="Delete your Clyvexa account" updated="October 31, 2026">
      <h2>In the app (immediate)</h2>
      <ol>
        <li>
          <a href={at("/app")}>Open Clyvexa</a> and log in.
        </li>
        <li>Choose &ldquo;My account&rdquo; at the top of the page.</li>
        <li>Choose &ldquo;Delete my account&rdquo; and confirm.</li>
      </ol>
      <p>Deletion happens right away and cannot be undone.</p>

      <h2>If you can&rsquo;t log in</h2>
      <p>
        Email [contact email] from the address you signed up with and ask us to delete your account. We will confirm
        and delete it within [30] days.
      </p>

      <h2>What is deleted</h2>
      <ul>
        <li>Your account (email and password hash) and your login sessions.</li>
        <li>All uploaded files, everything read from them, checks, letters, questions and practice calls.</li>
        <li>Payments entered in the refund finder.</li>
        <li>Your anonymized research records, if you had turned research sharing on.</li>
        <li>Your contributions to the billing error radar, if you had turned it on.</li>
      </ul>

      <h2>What is kept</h2>
      <ul>
        <li>
          Usage counts (such as &ldquo;a case was checked&rdquo;), with their link to you removed, so they can&rsquo;t be
          traced back to you.
        </li>
        <li>Feedback you gave on results, which never included your name, documents or account details.</li>
      </ul>
      <p>
        To delete just one bill instead, open it from your history and choose &ldquo;Delete&rdquo;. See the{" "}
        <a href={at("/privacy")}>privacy policy</a> for more.
      </p>
    </LegalPage>
  );
}
