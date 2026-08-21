# CareSetu Top-level UI Blueprint

**Status:** assembled 2026-08-21 from Wayfinder map [#178](https://github.com/sah-automation/CareSetu/issues/178), decisions [#179](https://github.com/sah-automation/CareSetu/issues/179)-[#188](https://github.com/sah-automation/CareSetu/issues/188) (ticket #189). This document synthesizes resolved decisions; it does not re-decide them. Where resolutions conflict, the conflict is flagged in §11 rather than silently resolved. The PRD (`docs/prd/project-prd.md`) and architecture docs remain authoritative for requirements; this blueprint governs UI design at wireframe-description fidelity.

| Section                        | Source resolution                           |
| :----------------------------- | :------------------------------------------ |
| §1 Design system               | #179 component library, #187 brand identity |
| §2 Navigation model and shells | #182 shell and navigation                   |
| §3 Public site                 | #180 homepage composition                   |
| §4 Auth surfaces               | #181 split auth and role entry              |
| §5 Patient app                 | #183 patient IA                             |
| §6 Doctor channel              | #184 doctor IA                              |
| §7 Partner channels            | #185 partner IA                             |
| §8 Operator console            | #186 operator IA                            |
| §9 Cross-cutting patterns      | #188 cross-cutting UX conventions           |
| §10 Gaps and implications      | carried from all resolutions                |
| §11 Conflicts flagged          | found during assembly (#189)                |
| §12 PHASE-2.6 scope sketch     | proposed, not yet ticketed                  |

---

## 1. Design system

### 1.1 Component library recommendation

Standardize on **shadcn/ui** (Radix primitive base, Tailwind v3 registry pinned), adopting components lazily per feature. **React Aria Components** adopted selectively for Intl-sensitive inputs (Hindi date/number fields). Hand-rolled Tailwind remains the pattern for leaf presentational components only.

Key evidence (from `docs/research/ui-component-library.md`, branch `research/component-library`):

- Bundle sizes measured Aug 2026: Radix dialog 12.6 KB gzip incl. deps; Headless UI whole package 63 KB gzip; react-aria-components whole package 271.5 KB gzip.
- shadcn explicitly supports Tailwind v3 apps and React 19 / App Router first-class since Oct 2024.
- React Aria has the strongest primary-source a11y evidence (VoiceOver/JAWS/NVDA/TalkBack testing) and built-in Intl - adopted per-widget, never wholesale.

Rejected as defaults: hand-rolled (full WAI-ARIA APG burden on a small team), Headless UI (component surface too small, fix-only cadence), Radix direct (strictly more work than shadcn over the same primitives), Base UI (too young; revisit later).

Migration posture toward the Phase 2.5 shell (Sidebar, Topbar, `types.ts` width constants, `icons.tsx`, PatientAuthWizard): **no rewrite, additive adoption**, with a CI bundle-size guardrail against NFR-003's 1.5 MB page budget.

### 1.2 Palette

Direction: deep teal primary + saffron-warm secondary on slate neutrals - trustworthy-and-warm. Teal carries health/calm without corporate-blue sterility; saffron adds warmth and Indian cultural resonance without consumer-playful saturation. All colors keep the existing token vocabulary in `apps/frontend/tailwind.config.ts`; component code references token names only.

| Token            | Value     | Tailwind ref | Role                                                                  |
| :--------------- | :-------- | :----------- | :-------------------------------------------------------------------- |
| `accent.DEFAULT` | `#0f766e` | teal-700     | Primary actions, links, active states. AA on white (~4.8:1)           |
| `accent.strong`  | `#115e59` | teal-800     | Hover/pressed, high-emphasis text on soft bg                          |
| `accent.soft`    | `#f0fdfa` | teal-50      | Tinted surfaces, selected rows, hero washes                           |
| `accent.border`  | `#99f6e4` | teal-200     | Focus rings, hairlines on tinted surfaces                             |
| `warm.DEFAULT`   | `#c2410c` | orange-700   | Saffron accent for text/icons/badges - AA on white (~5.4:1)           |
| `warm.mid`       | `#ea580c` | orange-600   | Fills, illustration accents, celebratory moments (large text/UI only) |
| `warm.soft`      | `#fff7ed` | orange-50    | Warm tint surfaces                                                    |

Migration note: only hex values change (`accent.DEFAULT` moves from seeded cyan-700 `#0e7490` to true teal-700 `#0f766e`). Token names unchanged; add the `warm` ramp. Semantic colors (`success`/`warn`/`danger`) and neutrals (`page.bg`, `surface`, `hairline`, `txt.*`) stay as-is. `warn` (amber) is reserved for system warnings; `warm` is brand-only - never use brand saffron to signal errors or warnings. Dark mode is out of scope for launch; tokens are structured so a dark ramp can be added later without renaming.

### 1.3 Typography

Single webfont family covering Latin + Devanagari: **Mukta** (Ek Type, SIL OFL, Google Fonts). Purpose-built as one harmonized family across Devanagari + Latin with verified native-quality Hindi glyphs (REQ-006). Weights in use: 400 body, 500 medium emphasis/UI labels, 600 headings/buttons, 700 hero only. Never below 400 for patient-facing text.

- Fallback stack: `'Mukta', 'Noto Sans Devanagari', 'Nirmala UI', system-ui, sans-serif`.
- Payload: self-host via `next/font/google` with unicode-range subsetting (latin + devanagari x 4 weights, ~120-160 KB woff2 total) - comfortably inside the NFR-003 budget. No second display family. Alternate if a variable font becomes a hard requirement: Anek Devanagari (same foundry).
- Scale: default Tailwind steps by convention - `text-xs` legal/disclaimers only; `text-sm` secondary UI and meta; `text-base` default body (patient app default); `text-lg`/`text-xl` card titles and section leads; `text-2xl`-`text-4xl` page titles; `text-5xl` desktop hero only.
- Line-height: body `leading-relaxed` (1.625) minimum globally; Devanagari matras need >= 1.6 to avoid clipping - never tighten body leading below that in either locale. Headings `leading-tight`.

### 1.4 Logo direction (concept)

**Bridge-arc wordmark.** "Setu" = bridge; the mark encodes the name directly.

- Mark: a single geometric arch (two piers + span) over a baseline; the baseline reads as the continuous longitudinal record, the arch as care bridging patient to the loop. Negative space under the span keeps it open, not boxed.
- Wordmark: "CareSetu" camelCase, one word, Mukta SemiBold, teal. Mark sits left of the wordmark at full lockup; alone as app icon/favicon (arch in a rounded square, white on teal).
- Production rules (downstream): SVG, geometric strokes, must survive monochrome (audit stamps, invoices, print), legible at 16px favicon size, works on `accent.soft` and white. Flat color only, no gradients required.

Final artwork production files are out of scope for this blueprint (map out-of-scope).

### 1.5 Tone of voice

For patients (Tier-3/4, moderate digital literacy):

- Plain short sentences, ~grade 6-8 reading level in EN; simple natural Hindi, comfortable Hinglish where patients expect it ("Report ready", "Book now").
- Reassuring competence, never fear or guilt: say what happens next at every step ("Dr. Sharma will review your summary today").
- AI honesty: AI output is always a draft ("AI draft - your doctor will verify"). Never "AI diagnosis", never present unverified output as final (mirrors ADR-0001 forced review).
- Consent-forward: every consent moment says who asks, what data, why, who sees it, in plain words.
- No fake urgency/scarcity, no dark patterns, no alarmist red marketing language.

For staff surfaces (doctor/partner/operator): terser and denser, jargon-honest, zero cutesy microcopy inside clinical workflows.

Bilingual parity: Hindi is a first-class locale, not a translation afterthought; both locales get equal design attention throughout this blueprint.

### 1.6 Trust cues

- "Verified by CareSetu" seal on doctors only after FEAT-014 activation; council registration number shown on doctor profiles and prescriptions (issuing doctor name + reg no attributed on every rx).
- Lab/chemist license numbers visible on partner profiles and order screens.
- Pre-summaries show "AI draft, reviewed by Dr. X on \<date\>" once forced review completes.
- Consent receipts: after each consent action, a plain-language confirmation of scope and validity.
- Data-safety strip on homepage: records shared only with your consent, revocable anytime.
- Human escalation: every automated flow shows a path to a person (clinic phone / operator contact).

### 1.7 Imagery and icons

- Real and local over stock-glossy: documentary-style photography of real people/settings from the beachhead region where possible, warm daylight.
- Illustration (if needed): flat geometric, teal/saffron palette, warm rounded forms - never clinical-white sterile, never 3D-render cliche.
- Icons: one consistent outline set (lucide, matching shadcn/ui), 1.5-2px stroke, rounded joins.
- Avoid: stethoscope stock cliches, western hospital imagery, fear imagery, corporate handshake gloss.

---

## 2. Navigation model and shells

### 2.1 URL groups

- **Public:** `/` (homepage), directory pages (`/doctors`, `/labs`, `/chemists`), static/info pages, `/login` (patient wizard entry), `/staff/login`, `/register/*` (provider registration wizard). Rendered in public chrome (marketing header/footer per §3), no auth required.
- **App:** route groups `(patient)`, `(doctor)`, `(partner)`, `(operator)` - each wrapped in its role's shell, never public chrome.
- **Transitional:** `/choose-role` - interim staff entry only, marked for deletion at Phase 5 (§4.6).

### 2.2 Guards (per ADR-0005)

- Edge middleware checks httpOnly-cookie presence only - no JWT parsing. Unauthenticated hits on app routes redirect to the correct entry by path prefix: patient-group deep links go to the patient OTP wizard, staff groups to `/staff/login`, preserving a return-url.
- Role enforcement is client-side in `AuthContext`/shell (wrong role or unauthenticated -> redirect); real authorization stays server-side at the API gateway RBAC. The UI guard is UX, not security.
- Public-directory CTAs that need an authenticated patient (book, consult) deep-link into the patient group and fall through the same redirect-with-return-url path.

### 2.3 Shell densities

Two shell densities from one component family:

```text
Light shell (patient)                      Full shell (doctor/partner/operator)
+--------------------------------+        +--------+---------------------------+
| top bar                        |        | sidebar| top bar        [account v]|
+--------------------------------+        |        +---------------------------+
| content (desktop: top-nav      |        | nav    | PageHeader                |
| above content; mobile: bottom  |        | items  | breadcrumbs (depth 2+)    |
| tabs below content)            |        |        | content                   |
+--------------------------------+        |        |                           |
| [bottom tab bar - mobile only] |        +--------+---------------------------+
+--------------------------------+        (mobile <lg: sidebar removed,
                                           bottom tab bar instead)
```

- **Light shell - patient app (§5):** top bar + bottom tab bar on mobile; slim top-nav on desktop. No sidebar at any width. Consumer feel, content-forward; serves the smartphone/4G persona and the page budget.
- **Full shell - doctor (§6), partner (§7), operator (§8):** collapsible left sidebar + fixed top bar on desktop/tablet. Task consoles keep persistent section nav.

### 2.4 Mobile navigation behavior

The Phase 2.5 icon-only rail collapse below 1024px does not serve the smartphone-first persona and is **retired**.

- Below `lg` (<1024px): sidebar removed from layout entirely. Bottom tab bar carries up to 5 primary destinations (icon + label); overflow destinations live under a "More" sheet. Top bar condenses but keeps the account menu.
- At `lg` and above: full shell shows the sidebar expanded by default; user can collapse it to an icon rail and that choice persists per role. Light shell swaps bottom tabs for the desktop top-nav.

### 2.5 PageHeader and breadcrumbs

- Every app page opens with a PageHeader block: H1 title, optional one-line description, primary action button right-aligned, sitting directly under the top bar inside the content padding.
- Breadcrumbs appear only at depth 2+ (`Section / Page`, e.g. `Records / Consent log`); they mirror URL structure; last crumb is plain text, never a link; home/root pages have none.
- On mobile, breadcrumbs collapse to a single back-link labeled with the parent section name.
- Max navigation depth is 3; anything deeper belongs in-page (tabs, sections), not in breadcrumbs.

### 2.6 Account menu

One account menu dropdown consolidates phone, role badge, switch-role, and logout as the single top-right cluster on every logged-in surface.

### 2.7 Nav-config schema

Tab-bar items and sidebar items come from **one nav-config source per role** (typed schema: label/href/icon/soon/count) driving sidebar, desktop top-nav (patient), and mobile bottom-tab variants - never two hand-maintained lists. Unbuilt entries render dimmed and non-interactive with the "Soon" badge convention; each surface decides which of its items launch as real pages (see §8.6).

### 2.8 Phase 2.5 shell verdicts (keep / kill / migrate)

| Component                  | Verdict                   | Notes                                                                                                                                                                                                                                                        |
| :------------------------- | :------------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Sidebar.tsx`              | Migrate                   | Pattern survives for full-shell roles; NAV_CONFIG becomes the shared typed schema (§2.7) driving sidebar and mobile tab variants; gains a `doctor` config; matchMedia auto-collapse replaced by CSS-driven responsive layout plus persisted user preference. |
| `Topbar.tsx`               | Migrate                   | Survives as shared top bar; left side gains a page-title/breadcrumb slot; right side consolidates into the account menu (§2.6).                                                                                                                              |
| `types.ts`                 | Migrate                   | `Role` union gains `"doctor"`; width/margin constants survive until the CSS-driven rework lands; `roleLabel` survives.                                                                                                                                       |
| `(dashboard)/layout.tsx`   | Migrate                   | Single generic dashboard group splits into per-role route groups each wrapped by the shared `<AppShell role=...>`; AuthProvider moves up so public pages can also read session state (header Login vs Dashboard button per §3.2).                            |
| `choose-role/page.tsx`     | Keep (interim), then kill | Stays the staff entry until Phase 5 MOD-001 staff auth exists (§4.6); its single-role direct-redirect logic lives on inside post-auth routing; the card-picker pattern reappears only for accounts holding multiple staff roles.                             |
| Icon-rail collapse <1024px | Kill                      | Replaced by bottom tab bar on mobile (§2.4).                                                                                                                                                                                                                 |

---

## 3. Public site (homepage)

Feel: Practo-like directory - search front and center, doctor cards, categories. Constraints honored: web-first (REQ-003), bilingual patient UI (REQ-006), 1.5 MB page budget (NFR-003), mobile-first persona, only activated providers surfaced (FEAT-004 Rule 1), verified-indicator truthfulness (FEAT-005).

### 3.1 Ordered sections

| #   | Section                 | Purpose                                                 | Content                                                                                                                                                                                                            | Key interactions                                                                                                                     |
| :-- | :---------------------- | :------------------------------------------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Header (sticky)         | Orientation + global entry                              | Wordmark; nav anchors: Doctors, Labs, Chemists; language toggle; auth area                                                                                                                                         | Sticky on scroll; mobile collapses to wordmark + toggle + Dashboard                                                                  |
| 2   | Hero + directory search | Get every visitor into a provider search within seconds | One-line value prop ("Find trusted doctors, labs and chemists near you"); search bar: provider-type select + free-text query + location chip defaulting to "Daltonganj"; secondary CTA "Get started" (patient OTP) | Submit -> `/directory?type=&q=&location=`; location editable, defaults to beachhead                                                  |
| 3   | Quick specialty chips   | Zero-typing search entry                                | 6-8 chips (GP, Pediatrician, Gynecologist, Dentist, Blood test, ...)                                                                                                                                               | Chip click pre-seeds `/directory` type/query filter                                                                                  |
| 4   | Category tiles          | Practo-style browse entry                               | Three primary tiles: Find Doctors / Find Labs / Find Chemists; top specialty links beneath each                                                                                                                    | Tile/link -> `/directory?type=...`; marketing navigation over directory filters, NOT disease browsing                                |
| 5   | Featured doctor cards   | Proof of supply; trust                                  | Live cards from public endpoint: name, specialty, verified indicator, consult type, area; 4-8 cards; "View all doctors" link                                                                                       | Card -> provider profile (`/providers/:id`); graceful "Directory launching soon in Daltonganj" empty state if no activated providers |
| 6   | How CareSetu works      | Explain the care loop in 3 steps                        | Step cards: find a provider -> share symptoms by voice (AI drafts a pre-summary your doctor reviews) -> prescriptions, reports and records stay in one place, shared only with your consent                        | Steps link to search / register entries                                                                                              |
| 7   | Trust & consent strip   | Serve the offline-trust persona                         | Short statements: credentials verified before listing; nothing shared without your consent; your records, your control; English + Hindi support                                                                    | Links to privacy/terms                                                                                                               |
| 8   | For Providers band      | Recruit supply side                                     | Three cards: Are you a doctor? / Lab? / Chemist? - one-line benefit + Register CTA; copy states "register now, our team verifies before you're listed"                                                             | Register -> open-registration flow with `?type=doctor\|lab\|chemist` preset (FEAT-014); never implies instant listing                |
| 9   | Final CTA band          | Convert remaining visitors                              | "Start with your health record" + Get started (patient OTP) + Dashboard                                                                                                                                            | Same role-entry model as §3.2                                                                                                        |
| 10  | Footer                  | Site map, legal, staff/operator entry                   | See §3.3                                                                                                                                                                                                           | -                                                                                                                                    |

Decisions embedded here:

1. Categories are marketing navigation over specialties, not disease browsing. Tiles/chips pre-seed directory filters (provider type + specialty). Disease-specific browsing/care programs are a recorded future feature gap (§10); homepage copy must not promise disease-based programs.
2. Doctor cards render live from the public directory endpoint once available, with a graceful empty state before supply exists. No fake/static provider cards.
3. Implementation replaces the current marketing stub `apps/frontend/src/app/page.tsx`.

### 3.2 Role-entry model

| Entry point                         | Anonymous visitor                                                                                                                                                 | Authenticated visitor                                                                          |
| :---------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------- |
| Header auth button                  | Label reads **Login** -> `/login` (patient phone-OTP wizard, existing Phase 2.5 flow)                                                                             | Label reads **Dashboard** -> session's role dashboard (`/patient`, `/partner`, or `/operator`) |
| Hero "Get started"                  | `/login` (patient OTP)                                                                                                                                            | Role dashboard                                                                                 |
| Register as Doctor / Lab / Chemist  | Open-registration flow with type preset (FEAT-014); works regardless of auth state; an authenticated patient starting a provider application enters the same flow | Same                                                                                           |
| Staff login (footer)                | Dedicated staff login route (split-auth, §4.2). Interim: `/choose-role`                                                                                           | Same                                                                                           |
| Operator console (footer, discreet) | `/operator` - the route itself enforces auth/RBAC; homepage advertises it nowhere but the footer link                                                             | Same                                                                                           |

Rule: the homepage never gates content on auth; every CTA is usable anonymously, and authenticated users are routed by their session role.

### 3.3 Header and footer contents

Header: wordmark (left) - nav anchors Doctors/Labs/Chemists - EN/Hindi toggle - Login/Dashboard button (right cluster). Mobile: wordmark + toggle + Dashboard.

Footer (4 columns):

- Patients: Find doctors / Find labs / Find chemists / How it works
- Providers: Register as doctor / Register as lab / Register as chemist / Staff login
- Company & legal: About / Privacy / Terms / Contact
- Meta row: (c) CareSetu - serving Daltonganj & peri-urban areas - Operator console (discreet link)

### 3.4 EN/Hindi toggle placement

Header right cluster, immediately left of the auth button; retained in the mobile sticky header. Choice persists (device localStorage when anonymous; profile field when logged in - mechanics in §9.2). All homepage copy ships EN + Hindi strings from day one (REQ-006).

---

## 4. Auth surfaces

### 4.1 Patient login (unchanged)

Header Login opens the existing PatientAuthWizard (phone OTP, Phase 2.5). Settled domain vocabulary applies as-is: E.164 normalization, 5-minute validity, attempt caps, resend latest-wins, phone lockout.

### 4.2 Staff login page (target state)

One professional login page at `/staff/login` serving doctor, lab, chemist, and operator. No role picker on the page - the role is derived server-side from the authenticated account, never user-chosen (avoids role-enumeration phishing).

Composition: centered card on a quiet professional backdrop - email field, password field (show/hide toggle), "Forgot password" link, sign-in button, inline error envelope (invalid credentials, locked account), divider, then a "New to CareSetu?" provider-registration block with type-preset CTAs (Doctor / Lab / Chemist) matching the §3.1 providers band.

Credential scheme per role: email + password for all staff roles. No OTP for staff. MFA is designed-in now as a conditional post-password step slot that renders only when the account has MFA enrolled; operator enrollment becomes mandatory when Phase 5 lands it. MFA implementation is out of scope until Phase 5.

### 4.3 Provider registration wizard (FEAT-014 open registration / gated activation)

Shared four-step skeleton for all provider types, type preset carried from the CTA:

1. **Account basics** - full name, email, password (strength-checked), optional mobile for alerts.
2. **Professional / business identity** - doctor: name as per degree, state medical council, city, languages spoken; partner: business name, address, service area, owner contact.
3. **Credentials upload** - doctor: council registration number, degree certificates, government photo ID; lab: business registration, accreditations (optional); chemist: drug license, shop license, owner KYC. Upload constraints follow the security standard's file discipline.
4. **Review & declarations** - summary of entries, truthfulness declaration, consent to credential verification, T&C acceptance, submit.

Submit creates the partner in `[Registered]`; automated checks (AMB-003 baseline) move it to `[Under Verification]`.

### 4.4 State-specific screens

- **Pending / Under Verification:** status card showing submitted-at, what is being verified, expected review window; explicit note "you are not listed publicly until activated"; help link. Any login while pending lands here instead of the channel home.
- **Rejected:** shows the specific failure reason (FEAT-014 scenario 2) plus a resubmission CTA - corrected credential upload re-enters `[Under Verification]`. The `Rejected -> Under Verification` resubmission edge is a PRD state-machine delta recorded in §10.
- **Active:** normal post-login routing.

### 4.5 Post-login routing rules

- Route by the login surface used: patient wizard -> patient app home; staff login -> the account's staff-role home (`/doctor`, `/partner`, `/operator`).
- Multi-role accounts keep all roles in `user.roles`; landing follows the surface used, and the Topbar switchRole remains the crossover mechanism. A scoped role picker appears only for accounts holding multiple staff roles.
- Fits ADR-0005 unchanged: dual httpOnly-cookie + localStorage JWT storage, middleware checks cookie presence only, role routing stays client-side in `AuthContext`.

### 4.6 Fate of /choose-role

Stays as the interim staff entry until Phase 5 MOD-001 staff auth exists, then is deleted.

---

## 5. Patient app (light shell)

Fixed inputs: §2 shell conventions and Persona-001 (moderate digital literacy, Hindi-first, 4G smartphone): big targets, minimal typing, voice-first wherever the PRD supports it. All primary CTAs carry bilingual labels.

### 5.1 Bottom tabs

`Home | Find Care | Start Visit | My Record | Inbox`

- **Start Visit** is the center tab: accent-colored circular button with a mic icon, label "Shuru karein / Start". The intake loop is the product core and gets a permanent big target.
- **My Record** absorbs chronic metric tracking (FEAT-018's tracking view) - metrics are record entries by definition.
- **Inbox** is first-class per FEAT-019 (WhatsApp stays notifications-only).
- **Bookings & Orders** and **Profile & Settings** live outside the tab bar: reachable from Home cards, post-action confirmations, and the account menu.

### 5.2 Home (`/patient`)

Vertical stack after greeting block (first name):

- **Decisions needed** strip (FEAT-013 partner-flow choices): out-of-stock substitute approve/refund, delivery-failure reschedule. Actionable inline; badge count mirrors into Inbox.
- **Due today** card (chronic-enrolled patients only): "Aaj ki BP entry / Log today's BP" - one tap opens the log form, pre-filled date.
- **Upcoming** card: next booking + active order status chips; tap to tracking screen.
- **Recent activity**: last intake/pre-summary status chip ("Doctor review pending"), recent record entries.
- Large **Start visit** CTA duplicates the center tab for discoverability.
- Empty states use illustration + single action, no jargon.

### 5.3 Find Care (`/patient/find`)

- Search input front-and-center (reuses the §3 homepage directory pattern), specialty chips below, type filter (Doctor/Lab/Chemist).
- Result cards: photo, name, specialty, languages spoken, fee, area; verified badge from activation state.
- Detail screens: doctor (credentials summary, clinic info, fee, Book CTA); lab/chemist (services, address/hours, order/upload-prescription CTA).
- Booking flow: slot/date pick (large grid targets) -> confirm screen that names what record access the booking needs -> consent moment (§5.10) -> confirmation screen with "Track this" deep link into Home Upcoming.

### 5.4 Start Visit - symptom intake (`/patient/intake`)

- Mode chooser: two oversized buttons, voice default-highlighted ("Boliye / Speak") vs text ("Likhein / Type").
- Voice screen: full-width mic target with recording state and live duration; playback + re-record before submit; EN/Hindi toggle always visible; poor/short audio prompts re-record or type, never silent-proceeds (FEAT-006 scenario 2).
- Text screen: large textarea, optional voice attach.
- Submit -> async "Structuring..." state -> result screen showing the pre-summary draft explicitly labeled "Draft - doctor saab verify karenge / doctor will verify"; low-confidence items show "doctor review needed" note (AMB-006 baseline: never presented as verified).
- Continuation CTA: "Book consultation with this summary" -> Find Care booking flow carrying the intake id.
- My intakes list (Captured / Structuring / Ready for Review states) reachable from Home recent activity.

### 5.5 My Record (`/patient/record`)

- Timeline of record entries (visits, prescriptions, lab results, metrics), reverse-chron, type filter chips.
- Entry detail: source, date, linked consent reference.
- Health tracking section (FEAT-018): BP/sugar trend view + daily log form; out-of-range values store normally with a neutral "shared with your care loop" note - no automated clinical interpretation (REQ-033); follow-ups surface as due nudges (30d/90d re-test).
- Consent log: every grant/revoke with requester, scope, timestamp; inline revoke (FEAT-002).
- Access audit (FEAT-003): who accessed what, when.
- Breadcrumb depth here: `Record / Consent log`, `Record / Health tracking`.

### 5.6 Inbox (`/patient/inbox`)

Notification feed with unread states: care-loop updates (pre-summary ready, booking reminders, order status), decision-needed alerts linking back to the Home decisions strip, system messages. Notification-preferences link (WhatsApp mirror is one-way at launch).

### 5.7 Bookings & Orders (`/patient/bookings`)

Segmented list (upcoming/past bookings, active/completed orders); detail screens show status timeline and the decision-needed actions when partner flows escalate.

### 5.8 Profile & Settings (`/patient/profile`)

Profile completion meter, personal details form, language preference, emergency contact, help link.

### 5.9 First-login profile-completion flow

Full-screen wizard immediately after first OTP login, maximum 3 steps, bilingual, skippable steps clearly marked:

1. **Required:** full name, age, gender; language preference. (Default value of the language field conflicts between sources - see §11.)
2. **Skippable:** chronic-condition interest toggles (BP/sugar) - switches on Home due-cards and tracking section.
3. **Skippable:** profile photo, area/address, emergency contact.

Gating rules:

- OTP identity gates login only. Browsing Find Care and viewing My Record are never gated.
- Name + age + gender gate care actions (intake submission, booking) - a named record is required for anything clinical. Missing fields trigger the wizard step inline at first care action, not a hard wall earlier.
- Area/address gates medicine-delivery checkout only.
- Skipped items resurface as gentle Home nudge cards and the Profile completion meter - never modal nagging.

### 5.10 Consent-moment UX pattern (designed once, reused everywhere)

Triggered by any care action requiring record access (booking with intake attached, lab accessing history, chemist filling a prescription). A bottom sheet, mobile-native:

1. Who is asking - requester name + verified badge.
2. What they will see - specific scope in plain Hindi/English ("Aapki pichli 3 mah ki prescriptions"), never blanket wording.
3. How long - per-action validity statement.
4. Two large buttons: "Allow / Anumati dein" and "Not now / Abhi nahi". Deny blocks the action with a plain explanation of what it unblocks - no dark patterns, no re-prompt spam.

Grant writes `consent_granted`; every sheet links to Record > Consent log; revocation lives there and inline on the originating object. Consent is never bundled: each action names its own access (per FEAT-002). Keyboard/focus behavior of this sheet is bound by §9.4.

---

## 6. Doctor channel (full shell)

Fixed inputs: §2 shell conventions and Persona-002 (time-constrained local physician, prefers voice-note/photo input): queue-first landing, few-tap flows. Canonical vocabulary from `CONTEXT.md` throughout: pre-summary, structuring confidence vs the 0.70 threshold, low_confidence flag, forced doctor review.

### 6.1 Top-level areas

Bottom tabs / sidebar entries: **Queue | Cases | Patients | Profile**

- **Queue (`/doctor`)** - the landing area. Two stacked sections:
  - Needs review: pre-summary cards awaiting verification, oldest-first; low_confidence cases carry an amber "Verify" chip and sort above clean ones. Each card: patient name/age, intake snippet, waiting time, one-tap "Review" deep-linking into the case's pre-summary tab.
  - Today: booked consults for today with stage chips; tap opens the case.
  - Empty state: "Sab clear hai / All caught up."
- **Cases (`/doctor/cases`)** - all active cases as a filterable list (stage chips: Pre-Summary / Consult Complete / Prescription Pending / Issued). Case detail is the workspace (§6.2).
- **Patients (`/doctor/patients`)** - consented-history directory: search over patients who have granted this doctor access; each opens a read-only history timeline. No consent = not listed here (and greyed in search).
- **Profile (`/doctor/profile`)** - public-profile preview toggle (exactly what Find Care shows patients), credential & activation status chip (Active / Under Verification), consultation fee, languages, availability sketch.

Breadcrumbs inside cases: `Cases / <patient> / Prescription`.

### 6.2 Case detail workspace (`/doctor/cases/<id>`)

Header: patient name/age/sex + a four-step case stepper (Pre-Summary -> Consult Complete -> Prescription Pending -> Issued), mirroring FEAT-008 state changes. Three inner tabs:

**a) Pre-summary tab**

- Structured-fields view beside/below the original intake (transcript text; audio playback link).
- Confidence display per the registry vocabulary; low_confidence renders the amber banner and enters verify mode (§6.4).
- Clean summary: single "Finalize" action records the timestamped attributed review and advances the case.

**b) History tab (consented view)**

- Only record sections the patient consented to share for this case; each section header shows provenance ("Consented 12 Aug, this visit").
- Sections never consented show a "Request access" CTA (fires a consent request; patient gets the §5.10 consent-moment sheet).
- Mid-case revocation greys the section immediately with a one-line notice - data already viewed stays in the case record, new access stops.

**c) Prescription tab**

- Stage-locked until (1) pre-summary finalized and (2) handshake marked complete (FEAT-008 scenario 2). The locked state names exactly what is missing with a one-tap jump to it.
- Unlocked: input row with two oversized buttons - "Boliye / Voice note" and "Photo" - plus optional typed addendum (Persona-002 input modes, FEAT-009).
- AI draft renders as editable item rows (drug / dose / frequency / duration); every doctor edit is tracked and surfaced ("2 items edited by you").

### 6.3 Consult handshake marking

- When the pre-summary is finalized, a prominent "Mark consult complete" action appears (doctor-initiated baseline per CFL-003).
- Confirm sheet: optional consult date/time + one-line note; submit fires the handshake, moves the case to Prescription Pending, and notifies the patient (`consult_marked_complete`). No video/chat surfaces anywhere - the platform only marks the off-platform event.

### 6.4 Forced-review interaction for low_confidence pre-summaries

Gate rule (ADR-0001/AMB-006): a low_confidence pre-summary is unusable as rx-draft input until a timestamped, attributed review is recorded. The UI makes that unmissable but frames it as routine double-check, never alarm:

- Entry: amber banner on the pre-summary tab and an amber "Verify" chip on the queue card - "AI yeh samjha - sahi hai? / AI understood this - please confirm." Amber, not red; no scary framing.
- Verify mode: structured fields grouped into three groups - identity, symptoms, history. Each group shows extracted values with a light confidence indicator; doctor taps "Sahi hai / Correct" per group or edits any field inline. Edits always win over extraction.
- Sign: after all three groups are confirmed or edited, a "Sign review" button records the timestamped, attributed review and finalizes the pre-summary. Skipping is impossible but the copy never scolds.
- Enforcement: handshake and prescription actions stay disabled with a plain pointer back to verify mode; deep links into gated tabs route through verify first.

### 6.5 Rx approval gate

- Never auto-issue (REQ-023): approval requires an explicit two-step confirm even with zero edits.
- Step 1 - "Review & approve": full-screen preview of the final prescription exactly as it will be issued, item rows with edit indicators, patient and case context on top.
- Step 2 - confirmation sheet: checkbox "Maine check kar liya / I have reviewed this prescription", then "Approve & issue" enables; issuing stamps timestamp + doctor attribution (`prescription_approved`, `edited_yn`).
- Reject path: "Reject draft" with a required short reason (`prescription_rejected`) returns the case for re-drafting; the patient is informed.
- Post-issue: status chip follows `[Rx: Fulfilled]` via partner events; doctor sees fulfillment state read-only.

---

## 7. Partner channels - lab and chemist (full shell)

Fixed inputs: §2 shell conventions and the partner personas: small-shop owners on phones - queue-and-action screens, minimal typing, few-tap status updates.

### 7.1 Verdict: one console, type-filtered

Lab and chemist share **one partner console at `/partner`**. The nav-config schema carries a `partner_type` filter per entry; queue contents, order-detail flows, and action sets render by type inside the same shell.

Rationale:

- Both personas share the identical operational rhythm: work arrives as routed orders, actions are status taps, money settles at the point of service.
- Settlements, order history, profile/credentials, and activation states are structurally identical for both types (FEAT-016/017/014) - separate consoles would duplicate them wholesale.
- One registration wizard (§4.3), one `partner` role in the session model, one activation state machine; the type is an attribute of the account, not a different product.
- Divergence stays possible later: if lab flows outgrow the shell, the nav-schema split gives a clean seam without a rewrite.

### 7.2 Shared nav map

Bottom tabs / sidebar entries: **Orders | History | Settlements | Profile**

- **Orders (`/partner`)** - landing area, action-first (§7.3).
- **History (`/partner/orders`)** - completed/cancelled orders, searchable by order ID or patient phone; read-only detail links.
- **Settlements (`/partner/settlements`)** - shared (§7.5).
- **Profile (`/partner/profile`)** - shared (§7.6).

Breadcrumbs: `Orders / <order id>`, `Settlements / Today`.

### 7.3 Orders queues

- **Lab:** sample-pickup queue - booked tests routed here with patient name, address/area, slot, test list; primary action "Mark collected". Below it, "Reports due" - orders in Result Pending with an upload nudge.
- **Chemist:** routed-prescription queue - new-rx alert cards (approved e-prescription routed to this shop), then Preparing / Out-for-delivery groups; each card's primary action advances status.
- Cards are big-target, one-tap; no typing required for routine advancement.

### 7.4 Order details (type-specific flows inside the shared shell)

**Lab order detail**

- Context block: patient identifiers, test list, mode (home pickup | pickup point | direct fallback), slot.
- Status stepper: Booked -> Sample Collected -> Result Pending -> Result Filed (FEAT-010).
- Actions: "Mark collected" (records `sample_collected`), "Upload report" (opens the binding flow, §7.5).
- No critical-value escalation surfaces anywhere (REQ-033): filing is filing.

**Chemist order detail**

- Prescription items list with the approved e-rx reference; zero-inventory rule visible: every item fulfilled by this shop (FEAT-012).
- Status stepper: Routed -> Preparing -> Out for Delivery -> Delivered.
- Few-tap actions: "Start preparing" -> "Out for delivery" (rider name optional) -> "Delivered".
- Out-of-stock: per-item "Not available" toggle opens a sheet stating exactly what the patient will be asked - partial fulfillment vs cancel (FEAT-013). Submitting notifies the patient and pauses the order; the partner cannot silently substitute items. Until the patient chooses, the order shows "awaiting patient choice"; the recorded choice (`patient_choice_partial|cancel`) unlocks the matching continuation.
- Delivery failure: "Delivery failed" action with a reason pick (unreachable / address issue) records `delivery_failure`; screen then shows "patient choosing retry path" and renders the outcome when made (off-platform direct vs platform retry/reroute). The choice UI itself lives in the patient app decisions-needed strip (§5.2) - partner screens only present state and options already recorded.

### 7.5 Report upload + match/binding flow (lab, per FEAT-011)

Three steps, reachable from order detail or a standalone "Quick upload" for walk-in paper reports:

1. **Capture:** photo of the report or PDF select. No parsing at launch (REQ-026 deferred) - nothing is read from the document.
2. **Binding (the protection step):** pick the order from the pending-result list or key in the order ID; the screen then shows side-by-side confirmation - entered order ID + patient name/age against the chosen order's stored identifiers. Any mismatch hard-blocks with a visible error and the report is not filed (FEAT-011 scenario 2). Matching requires an explicit two-tap confirm ("Match & file") recording `report_matched`.
3. **Filed confirmation:** success screen linking the order; states Uploaded -> Matched -> Filed all recorded.

### 7.6 Settlements (shared, FEAT-016/017)

- Record-outcome pattern: completing the final action (Delivered for chemist, report filed + service complete for lab) prompts "Payment received?" with two oversized buttons - Cash / UPI - amount pre-filled from the order total; platform-facilitated appears only when a risk signal exists (exception path, reason noted). Platform records the outcome only; receipts stay partner-issued.
- Tabs within the page: Today / This week totals, per-order settlement list with type chips (cash|upi|platform_facilitated), facilitation flags highlighted.
- Cancellations: partner-initiated cancellation records `order_cancelled (partner)`; refund is always partner-direct - the screen states plainly that the platform holds/processes nothing (REQ-036); each partner's own cancellation policy text is shown alongside (policy inherited per FEAT-017).

### 7.7 Credential/profile surfaces (shared)

- Activation status chip rendered in-profile and passively beside the shop name on every screen: Registered / Under Verification / Active / Rejected (FEAT-014 states). Rejected shows the specific failure reason plus a resubmit CTA re-entering the registration wizard's credentials step (§4.3 flow).
- Public-listing preview: exactly what patients see in Find Care - business name, photo, address/hours, service area, contact.
- Editable: hours, address, service area, owner contact, and the cancellation policy text (shown to patients pre-booking per FEAT-017 scenario 1).
- Credentials section mirrors the uploaded documents' verification status; re-upload follows the §4.3 upload discipline.

---

## 8. Operator console (full shell)

On the §2 full shell (collapsible sidebar + topbar desktop, bottom tabs below `lg`, one nav-config schema, PageHeader block, Soon-badge convention, account menu top-right).

### 8.1 Top-level areas (4)

**Home | Verifications | Disputes | Audit.**

Access-history queries are not their own area: record-access events already live in the append-only audit store (FEAT-020 Rule 1), so access history is a purpose-built query lens inside Audit (§8.5). Four entries keep the mobile 5-tab rule comfortable and leave room for a future Partners lookup entry.

### 8.2 Home - task-first

Two action cards dominate above the fold; no vanity metrics:

- **Verifications card:** pending count, oldest-waiting age, 48h-SLA breach warnings (KPI-004 activation cycle). Deep-links into the queue pre-filtered to actionable items.
- **Disputes card:** open count, oldest waiting. Deep-links into the disputes queue.
- Below: compact recent operator-decisions feed (approve/reject events with actor + timestamp).

### 8.3 Verifications - intake-only

- One queue of Under Verification partners, oldest-first default sort (KPI-004 scenario 2), filterable by partner type.
- Detail page shows the FEAT-014 submission: business/professional identity plus uploaded credentials, with automated pre-check results surfaced for flagged cases (AMB-003 baseline: automated checks + manual review).
- Actions: Approve, or Reject-with-reason - the reason feeds the §4.4 rejected screen and resubmission loop.
- Already-live partners appear only in a read-only lookup. No suspend/deactivate controls in this blueprint - activation lifecycle management beyond intake is out of scope here.

### 8.4 Disputes - facilitate-only (Soon badge at launch)

Resolves the PRD tension (Persona-005 "moderates disputes" vs REQ-032/REQ-036 pure-facilitator posture):

- Operator sees dispute context: order timeline plus both parties' statements.
- Operator posts facilitation notes visible to both sides.
- Operator closes as resolved / withdrawn / unresolved.
- The operator never rules on money and never triggers refunds - partners settle directly per §7.6.

This workspace design is recorded for when a backing dispute FEAT lands; until then Disputes renders as a Soon badge (§8.6). The missing dispute-feature spec is a recorded gap (§10).

### 8.5 Audit - read-only, two lenses

- Event log: all audit events, filters by type/actor/time range; tamper-attempt events carry a distinct highlight (FEAT-020 scenario 2).
- Access history: purpose-built query - pick patient or actor + time range; results show who accessed which record when (NFR-002/KPI-006 record-access logging).
- Strictly read-only throughout; CSV/export deferred.

### 8.6 Launch set for PHASE-2.6

Real pages: Home, Verifications queue + detail, Audit event log, Access history (FEAT-015/FEAT-020 are Must Have; MOD-011 audit backend exists). Disputes renders as a Soon badge until a backing FEAT lands.

---

## 9. Cross-cutting UX patterns

These bind every surface section above retroactively.

### 9.1 Loading, empty, and error states

Family: skeletons + banner/toast split (shadcn-native).

- Loading: skeleton placeholders matching the final layout for first content load of any list/detail canvas (doctor cards, queue, orders, audit table). In-place mutations use a spinner inside the triggering button (disabled while pending) - never a full-page spinner. The Soon badge convention (§2.7) covers not-yet-built areas.
- Empty states: every list/canvas ships one. Anatomy: plain-language what-this-is, why it's empty, exactly one next action ("No reports yet - reports your lab uploads appear here. [Book a lab test]"). Never blame the user; empty is styled as neutral/soft (`accent.soft`), never like an error.
- Errors render at four scopes:
  - Field-level - inside forms, under the input (see §9.5).
  - Inline - card/row-scoped failure (one doctor card fails to load its photo): quiet retry link in place.
  - Banner - page-scoped failure: dismissible banner at top of content area with a Retry action and the short `trace_id` for support correlation.
  - Toast - transient confirmations and background failures that must not interrupt the current task.
- Retry discipline (api-standards §5 + PRD §5.2): auto-retry only network failures/`5xx`, max 3 attempts with backoff; never auto-retry `4xx`; honor `Retry-After` on `429`. Voice intake upload follows §5.2 verbatim: auto-retry up to 3x, then prompt to re-record.

### 9.2 Bilingual mechanics

Model: profile field + session toggle.

- Logged-in patients: language is a profile field (`"en" | "hi"`). The header toggle switches the session instantly and persists to the profile.
- Anonymous visitors (public site): same toggle persists to device localStorage.
- Server-initiated notifications (WhatsApp/SMS) read the profile field - satisfies REQ-006 Rule 2. The default value until set is flagged as a conflict in §11; the first-login profile wizard (§5.9) asks language alongside required basics.
- `<html lang>` must track the active locale (current shell hardcodes `lang="en"` - flagged for PHASE-2.6 fix, §10/§12). Devanagari rendering rules per §1.3: body line-height >= 1.6 in both locales.
- Mechanics: no i18n framework at launch. Generalize the proven OTP-wizard pattern - typed per-locale string dictionaries with a `t(key)` accessor; every patient-facing copy goes through it. Staff surfaces are English-first but use the same mechanism so Hindi can be added later without re-plumbing.
- Bilingual parity rule: a string key missing from either locale fails review - no shipping EN-only keys in patient surfaces.

### 9.3 Low-bandwidth posture

NFR-003 sets the floor: initial load <= 5s on 4G, page weight <= 1.5 MB, supported downlink >= 1 Mbps, and explicitly no optimization below this baseline. Light-touch tolerance, not offline-first:

- Image discipline: AVIF/WebP with sized `srcset`, lazy-load below-fold images; no autoplay media anywhere.
- Every data fetch has an explicit, visible retry affordance after failure (never a silent spin).
- Mutations are double-submit-safe: button disabled+pending state during flight, `Idempotency-Key` header per api-standards §5.
- Uploads (voice intake, report photos) show progress with cancel/re-record per §5.2 of the PRD error-handling fallbacks.
- No service-worker sync queue / offline-first PWA at launch. Read-only caching of last-seen lists is permitted later if KPIs demand it - out of scope here.

### 9.4 Accessibility floor

WCAG 2.1 AA is a hard floor, enforced by the existing axe CI gate (TEST-C2) plus manual spot-checks on critical loops (auth wizard, booking, rx approval):

- Text contrast 4.5:1 (3:1 for large text) - brand tokens from §1.2 were chosen AA-safe (`accent.DEFAULT`, `warm.DEFAULT` pass on white).
- Complete keyboard operability, including the consent-moment bottom-sheet pattern (§5.10): focus trapped while open, Escape closes, focus returns to trigger.
- Visible focus ring everywhere using `accent.border`; never `outline: none` without replacement.
- Labeled controls (no placeholder-only labels); touch targets >= 44px.
- Status messages announced: form errors via `aria-describedby` + assertive live region on submit failure; async success/failure toasts via polite live region.
- `prefers-reduced-motion`: skeleton pulse and animations disabled.
- Correct `lang` attribute per active locale (feeds screen-reader Hindi pronunciation).

### 9.5 Form validation and error-envelope presentation

The API envelope is `{code, message, trace_id, details}` (api-standards §2); user-visible copy lives in the client, keyed on the stable `code`.

- Client-side validation first: mirror server schemas client-side; validate on blur and on submit. Failed submit shows a summary block above the form, moves focus to the first invalid field, and announces the count of errors.
- Server `422` mapping: `details[]` entries map `path -> field` and render field-level; unmapped paths fall back to the form summary.
- Copy rules by taxonomy (error-handling-observability §1):
  - Expected `4xx` (`CONSENT_DENIED`, mismatch, out-of-stock): calm, specific, actionable - use the PRD §5.2 fallback strings verbatim where one exists ("This report does not match the order/patient", "Item unavailable", "Delivery failed", "Platform payment unavailable").
  - Operational `5xx`: "Something went wrong on our side. Retry" + banner with short `trace_id`.
  - Third-party `502/503/504`: degrade messaging naming the alternative where one exists (PRD §5.2 cash/UPI fallback), never a dead end.
  - Security-class failures: neutral wording, zero internal detail.
- Never show raw codes, stack traces, or envelope JSON to users; never log PHI/OTPs/tokens from client-side error reporting (NFR-SEC applies client-side too).
- Both locales get equal-quality error copy - parity rule from §9.2 applies.

---

## 10. Gaps and backend implications register

Carried verbatim from the resolutions so downstream phase planning cannot lose them. None are designs; all are notes for requirements/backend efforts.

| #   | Item                                                                                                                                                                                                                                                                                                                                                                                 | Source     |
| :-- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------- |
| G1  | Disease-specific browsing/care programs are a future feature gap; homepage copy must not promise disease-based programs.                                                                                                                                                                                                                                                             | #180       |
| G2  | Public directory search endpoint: unauthenticated read over activated providers only; filters: provider type, specialty, free-text, location; wider-area fallback per FEAT-004 Scenario 2. Public provider-card payload carries verified-safe fields only. Anonymous telemetry `directory_search` / `provider_selected` needs nullable/cohort-tagged actor id.                       | #180       |
| G3  | MOD-001 staff identity records (email+password credential type, hashing per security standard, forgot/reset-password, email ownership check), session issuance extension, partner state-machine endpoints (submission with uploads, status query, rejection-reason, resubmission edge, `partner_rejected` notification hook), MFA (TOTP) endpoints - all Phase 5 planning territory. | #181       |
| G4  | `Rejected -> Under Verification` resubmission edge is a small PRD state-machine delta to record during Phase 5 planning.                                                                                                                                                                                                                                                             | #181       |
| G5  | Profile-completion gating needs a lightweight profile-fields endpoint (MOD-001 territory, Phase 5 planning note).                                                                                                                                                                                                                                                                    | #183       |
| G6  | Partner events (FEAT-013) fan-out to the patient decisions-needed surface - event registry addition to trace during Phase 5 planning.                                                                                                                                                                                                                                                | #183, #185 |
| G7  | Doctor-initiated consent request event reaching the patient inbox (§5.10 pattern) - trace in the event registry during Phase 5 planning alongside staff-auth work.                                                                                                                                                                                                                   | #184       |
| G8  | Verify/sign needs a review-attribution write endpoint distinct from simple finalize (stores per-group confirmations + editor identity).                                                                                                                                                                                                                                              | #184       |
| G9  | Dispute-feature PRD gap: moderation needs a backing FEAT (dispute lifecycle model) before the Disputes area can ship.                                                                                                                                                                                                                                                                | #186       |
| G10 | Verification detail depends on FEAT-014 credentials-upload artifacts being retrievable by operators - API-surface note for phase planning.                                                                                                                                                                                                                                           | #186       |
| G11 | `<html lang>` hardcoded `"en"` in the current shell - flagged for PHASE-2.6 fix (§9.2).                                                                                                                                                                                                                                                                                              | #188       |

---

## 11. Conflicts flagged during assembly

Per the assembling ticket's contract, conflicts are flagged, not silently won:

| Flag | Tension                                                                                                                                                                                    | Status                                                                                                                                  |
| :--- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------- |
| C1   | Default profile language for a patient who never sets it: #183's wizard step 1 says "language preference (defaults Hindi)" while #188 says the profile field defaults to `"en"` until set. | Open - one-line decision for repo owner; affects §5.9 step 1 and §9.2 default only. Everything else about the language model is agreed. |

No other cross-resolution conflicts were found: interim `/choose-role`, shell verdicts, tab compositions, partner-direct refunds vs operator facilitation-only, and the Soon-badge launch set all agree across their citing tickets.

---

## 12. Proposed PHASE-2.6 scope sketch

Candidate next UI implementation phase. This sketch proposes scope only - actual phase ticketing is a separate effort (map out-of-scope). Candidate ID "PHASE-2.6" slots between the Phase 2.5 frontend foundation work and the roadmap's later phases; the roadmap owner should ratify the number when ticketing.

### 12.1 Candidate goal

Turn the Phase 2.5 skeleton into the resolved public face and shared app chassis: ship the resolved homepage, rework the shell to the §2 model, stand up the split-auth page skeletons, and add the patient profile-completion skeleton - everything wired to what exists today, with clearly-marked integration points where backend legs land in later phases.

### 12.2 Candidate workstreams

- **W0 Foundations (enabling, mandated by resolutions):**
  - Palette token migration per §1.2 (hex swap + `warm` ramp; token names unchanged).
  - Mukta self-hosting per §1.3 via `next/font/google` with unicode-range subsetting.
  - shadcn/ui groundwork per §1.1 (lazy adoption start + CI bundle-size guardrail vs NFR-003).
  - Typed STRINGS dictionary generalization from the OTP wizard (§9.2) + `<html lang>` locale-tracking fix (G11).
- **W1 Homepage composition:** implement §3.1 sections 1-10 replacing `apps/frontend/src/app/page.tsx`; live doctor cards against the public endpoint when it exists with the graceful empty state before supply; server-rendered, lazy below-fold data for NFR-003.
- **W2 Shell rework:** execute the §2.8 verdicts - shared `<AppShell role=...>`, per-role route groups, nav-config schema (§2.7), bottom tab bar + More sheet replacing the killed icon-rail, PageHeader block + breadcrumb components (§2.5), account menu consolidation (§2.6), AuthProvider hoist.
- **W3 Split-auth pages:** `/staff/login` composition with the conditional MFA slot rendered only when enrolled (inert until Phase 5); four-step provider registration wizard skeleton (§4.3); pending/rejected state screens (§4.4) reachable post-login; post-login routing rules (§4.5). Staff authentication itself stays Phase 5 (G3) - pages render against the existing session model and mark integration points; `/choose-role` remains the working interim entry (§4.6).
- **W4 Profile-completion skeleton:** first-login wizard (§5.9) with gating rules, profile completion meter, nudge cards; consent-moment bottom-sheet pattern component built once (§5.10) for reuse by later phases.

### 12.3 Suggested sequencing

W0 first (everything consumes tokens/fonts/dictionaries), then W2 (shell unblocks all per-role surfaces), then W1 (independent of W2, can parallel W2), then W4 and W3. Order beyond W0 is a proposal for the ticketing effort, not a decided dependency graph.

### 12.4 Explicitly deferred by this sketch

- Backend staff auth/MFA (Phase 5, G3/G4) - pages only in PHASE-2.6.
- Detailed per-phase UI specs for the doctor/partner/operator channels - downstream efforts cut from this blueprint per the map.
- Final logo/artwork production files (§1.4 direction only).
- Disputes backing feature (G9), offline-first/PWA, dark mode, CSV export from Audit.

---

_End of blueprint. Sources: resolution comments on issues #179-#188 under map #178; brief `docs/agents/briefs/UIBP-T11-assemble-blueprint.md`._
