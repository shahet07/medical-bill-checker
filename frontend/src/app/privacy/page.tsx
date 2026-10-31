import type { Metadata } from "next";
import LegalPage from "@/components/site/LegalPage";

export const metadata: Metadata = { title: "Privacy policy · Clyvexa" };

export default function Privacy() {
  return (
    <LegalPage title="Privacy policy" updated="October 31, 2026" draft>
      <p>
        Clyvexa is run by [operator name] (&ldquo;we&rdquo;). This policy explains what we collect when you use Clyvexa,
        why, how long we keep it, and what you can do about it. Contact: [contact email].
      </p>

      <h2>What we collect</h2>
      <ul>
        <li>
          <strong>Your account:</strong> your email address and a password hash (Argon2id). We never store your password
          itself.
        </li>
        <li>
          <strong>Documents you upload:</strong> medical bills and Explanation of Benefits statements, as PDF files or
          photos. These can contain health information, such as names of services and diagnosis or procedure codes.
        </li>
        <li>
          <strong>What we read from them and your results:</strong> the totals and lines read from your documents, any
          corrections you make, the checks found, explanations, letters, questions you ask and practice calls.
        </li>
        <li>
          <strong>Payments you enter</strong> in the refund finder.
        </li>
        <li>
          <strong>Feedback</strong> you choose to give on results.
        </li>
        <li>
          <strong>Usage events,</strong> such as &ldquo;signed up&rdquo;, &ldquo;case checked&rdquo; or &ldquo;letter
          created&rdquo;, linked to a keyed one-way hash rather than your account ID.
        </li>
      </ul>
      <p>
        We use one cookie, to keep you logged in. We do not use advertising or tracking cookies, and we do not run
        third-party analytics on these pages.
      </p>

      <h2>How we use it</h2>
      <ul>
        <li>To read your documents, run the checks, and write explanations and letters for you.</li>
        <li>To let you come back to your results.</li>
        <li>To keep the service secure, for example by limiting repeated login attempts.</li>
        <li>To understand how the service is used and improve it, from usage events and feedback.</li>
      </ul>
      <p>We do not sell your information or use it for advertising.</p>

      <h2>AI services that process your documents</h2>
      <p>
        To read your documents and write explanations, their content is sent to an AI provider: [Google (Gemini API)
        and/or Anthropic (Claude API)]. The provider processes it under its terms for API customers. [State whether the
        provider may retain or use this data, which depends on the plan used. A free plan may allow the provider to use
        submitted data to improve its products; such a plan must not be used for real patient documents.]
      </p>

      <h2>Optional sharing (off unless you turn it on)</h2>
      <ul>
        <li>
          <strong>Research:</strong> if you agree, we keep anonymized results (procedure codes, amounts and the checks
          found) without your name, provider, account numbers, dates or files. You can turn this off in your account at
          any time, and deleting a case or your account deletes its research record.
        </li>
        <li>
          <strong>Billing error radar:</strong> if you agree, the provider&rsquo;s name and the kind of error found are
          added to a shared count. A pattern is shown to others only once at least 10 different people have reported it,
          and never with who reported it.
        </li>
      </ul>

      <h2>How long we keep it</h2>
      <ul>
        <li>Uploaded files: deleted 24 hours after upload.</li>
        <li>Results (what was read, checks, letters): deleted after 90 days.</li>
        <li>Login sessions: expire after 14 days.</li>
        <li>
          Your account: until you delete it. Deleting it immediately deletes your files, results and research records.
        </li>
        <li>
          Feedback and usage events: kept for analysis. When you delete your account, events lose their link to you.
        </li>
      </ul>

      <h2>How we protect it</h2>
      <p>
        Files and results are encrypted with AES-256-GCM before they are stored. Connections use HTTPS. Login session
        tokens are stored only as hashes. Before upload, the photo quality check runs on your own device. No system is
        perfectly secure; if a breach affects your information, we will notify you as the law requires.
      </p>

      <h2>Your choices and rights</h2>
      <ul>
        <li>Delete any result, or your whole account, at any time from &ldquo;My account&rdquo;.</li>
        <li>Turn research sharing and the billing error radar on or off at any time.</li>
        <li>
          Ask us for a copy of your information, or to correct or delete it, at [contact email]. Depending on where you
          live (for example California or Washington), you may have further rights under state privacy or consumer
          health data laws.
        </li>
      </ul>
      <p>
        See also <a href="/delete-account">how to delete your account</a>.
      </p>

      <h2>Children</h2>
      <p>
        Clyvexa is for adults 18 and over. A parent or guardian can check a child&rsquo;s bill from their own account.
      </p>

      <h2>Changes</h2>
      <p>If we change this policy in a way that matters, we will say so on this page and in the app before it applies.</p>
    </LegalPage>
  );
}
