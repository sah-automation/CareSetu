import { Lock } from "lucide-react";

// #658 (one history read, #645 US-63): the calm lock that both doctor
// surfaces - the case workspace History tab and the patient profile - use for
// a denied / not-shared section. Failure-fails up to the caller purely in
// copy: give it the section's title and body. One shared card means the two
// surfaces cannot drift into different denial renderings.

export function NotSharedCard({
  title,
  body,
}: {
  title: string;
  body: string;
}) {
  return (
    <div
      data-testid="locked-section"
      className="flex items-start gap-3 rounded-lg border border-hairline bg-surface px-4 py-4"
    >
      <Lock
        className="mt-0.5 h-4 w-4 shrink-0 text-txt-muted"
        aria-hidden="true"
      />
      <div>
        <p className="text-sm font-medium text-txt">{title}</p>
        <p className="mt-0.5 text-sm text-txt-muted">{body}</p>
      </div>
    </div>
  );
}
