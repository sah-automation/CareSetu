// PHASE-2.6 T03 (#194): app-wide typed bilingual string dictionaries,
// generalized from the proven patient-auth-wizard string table (blueprint
// §9.2, spec #191 decision 5). No i18n framework: typed per-locale objects
// with keys grouped by surface (`auth.*`, later tickets add `home.*`,
// `nav.*`, ...) so new sections land without merge friction.
//
// REQ-006 bilingual parity: every key must exist in both locales with the
// same shape. `hi` is annotated as `Dictionary` (= typeof en) so TypeScript
// rejects a missing or reshaped key at compile time; the bilingual parity
// unit test re-enforces it mechanically at runtime (a key missing from
// either locale fails the suite).

/**
 * The locales the app ships, with their native (language-internal) display
 * names. A native name never translates with the surrounding locale, so these
 * live here on the i18n config surface (coding-standards §9.1/§9.2 - a locale
 * change is a single edit, not a source sweep) rather than as scattered JSX
 * option literals or in the per-locale dictionaries. Every language picker
 * renders from this list, and Lang is derived from it so the code set exists
 * once.
 */
export const SUPPORTED_LOCALES = [
  { code: "hi", nativeName: "हिंदी" },
  { code: "en", nativeName: "English" },
] as const;

export type Lang = (typeof SUPPORTED_LOCALES)[number]["code"];

const en = {
  // auth.* surface - the patient OTP wizard's copy, moved verbatim from
  // otpState.ts (PHASE-2 T9, #60). Byte-stable by contract: the deployed
  // live smoke asserts parts of it literally (spec #191 decision 16).
  auth: {
    brand: "CareSetu",
    tagline: "Your health, connected",
    phoneLabel: "Mobile number",
    phonePlaceholder: "10-digit mobile number",
    getCode: "Get verification code",
    verify: "Verify & continue",
    resend: "Resend code",
    backToEdit: "Edit number",
    codeLabel: "Verification code",
    codeHint: "6-digit code sent by SMS to",
    codeExpires: "Code expires in",
    resendIn: (s: number) => `Resend in ${s}s`,
    attemptsLeft: (n: number) =>
      `${n} ${n === 1 ? "attempt" : "attempts"} left`,
    noAttempts: "No attempts left. Request a new code.",
    wrongCode: (n: number) =>
      `Wrong code. ${n} ${n === 1 ? "attempt" : "attempts"} left.`,
    badPhone: "Enter a valid 10-digit Indian mobile number.",
    shortCode: "Enter the full 6-digit code.",
    lockout: (m: number) =>
      `Too many failed attempts. Verification locked for ${m} min.`,
    resendEarly: (s: number) => `Cooldown active. Resend in ${s}s.`,
    expiredOrUsed:
      "This code has expired or was already used. Request a new one.",
    latestWins: "A new code was sent. The previous code is no longer valid.",
    duplicateNotice:
      "This number is already registered - verifying logs you in.",
    verifiedTitle: "Identity verified",
    verifiedBody: "Your number is verified and your session is ready.",
    goHome: "Go to CareSetu home",
    welcome: "One verified identity for your entire health journey.",
    stepPhone: "Phone",
    stepVerify: "Verify",
    stepDone: "Done",
    stepProgress: "Sign in progress",
    valueProps: [
      "One stable identity - no duplicate accounts",
      "Your record stays yours, shared only with your consent",
      "Works in English and Hindi",
    ],
    networkError: "Could not reach the server. Check your connection.",
    smsFailed: "We could not send the code. Try again in a moment.",
    suspendedNotice:
      "This number is suspended. Contact support for assistance.",
    notRegistered:
      "This number was never registered. Go back and get a code first.",
    sessionTitle: "You're signed in",
    sessionBody: "Your identity is verified and your health journey is ready.",
    signedInAs: (phone: string) => `Signed in as ${phone}`,
    signOut: "Sign out",
  },

  // doneScreen.* surface - #536: the shared verified-login handoff screen
  // rendered after a successful OTP verify (patient flow #536; the doctor
  // flow #537 consumes the same component). #581 made it a loading mask
  // rather than a countdown: `openingDashboard` is the one status line for
  // the whole life of the screen and names the indeterminate progress
  // indicator, and no key here carries a digit. `goToDashboard` is the
  // always-available CTA, which navigates through the host's own readiness
  // gate (#578's hook). The remaining keys are the doctor handoff's
  // practice/destination facts (US-3): values come from data, labels from here.
  doneScreen: {
    openingDashboard: "Opening your dashboard",
    goToDashboard: "Go to Dashboard",
    practiceLabel: "Practice",
    specialtyLabel: "Specialty",
    destinationLabel: "Destination",
    consoleDestination: "Doctor console",
  },

  // staffAuth.* surface - PHASE-2.6 T10 (#201): the split-auth staff entry
  // (/staff/login), partner status screens, and the scoped staff-role picker.
  // Pages only this phase: submits name Phase 5 honestly, never fake success.
  staffAuth: {
    login: {
      brand: "CareSetu",
      subtitle: "Staff sign-in - doctor, lab, chemist",
      heading: "Sign in",
      emailLabel: "Email",
      emailPlaceholder: "you@example.com",
      passwordLabel: "Password",
      showPassword: "Show",
      hidePassword: "Hide",
      forgotPassword: "Forgot password?",
      signIn: "Sign in",
      phoneLabel: "Phone number",
      phonePlaceholder: "10-digit mobile number",
      phoneInvalid: "Enter a valid phone number.",
      mfaCodeLabel: "Authentication code (2FA)",
      mfaHelp: "Enter the 6-digit code from your authenticator app.",
      mfaSubmit: "Verify code",
      codeRequired: "Enter the 6-digit code.",
      codeInvalid: "The code must be exactly 6 digits.",
      newHereTitle: "New to CareSetu?",
      newHereBody:
        "Register your practice or business - our team verifies before you are listed.",
      registerDoctor: "Doctor",
      registerLab: "Lab",
      registerChemist: "Chemist",
      noRolePickerNote:
        "No role picker here by design: at sign-in your role comes from your account, never chosen by hand. Patients use the phone OTP wizard instead.",
      interimNote: "Interim staff entry stays until Phase 5:",
      chooseRoleLink: "choose role",
      emailInvalid: "Enter a valid email address.",
      passwordRequired: "Enter your password.",
      summaryTitle: (n: number) =>
        `${n} ${
          n === 1 ? "field needs" : "fields need"
        } attention before you continue.`,
      phase5Notice:
        "Sign-in is not connected yet: staff authentication arrives in Phase 5. Nothing was sent or saved just now.",
      invalidCredentials: "Incorrect email or password.",
      accountLocked:
        "This account is temporarily locked after repeated failures. Try again in about 15 minutes or reset your password.",
      genericError:
        "Something went wrong, please check your credentials and try again.",
      invalidOperatorCode: "Invalid authentication code. Please try again.",
      // Partner phone-OTP mode (F014-T07 #467): partner staff sign in with
      // phone + SMS code, mirroring the patient wizard's interaction copy.
      getCode: "Get verification code",
      // #573: the code step's own top-level heading, so a partner can tell which
      // step they are on without reading the copy around it. Deliberately not
      // `heading` ("Sign in"): that names the page, this names the step.
      codeStepTitle: "Enter the verification code",
      codeLabel: "Verification code",
      codeHint: "6-digit code sent by SMS to",
      codeExpires: "Code expires in",
      resend: "Resend code",
      backToEdit: "Edit number",
      resendIn: (s: number) => `Resend in ${s}s`,
      attemptsLeft: (n: number) =>
        `${n} ${n === 1 ? "attempt" : "attempts"} left`,
      noAttempts: "No attempts left. Request a new code.",
      wrongCode: (n: number) =>
        `Wrong code. ${n} ${n === 1 ? "attempt" : "attempts"} left.`,
      shortCode: "Enter the full 6-digit code.",
      lockout: (m: number) =>
        `Too many failed attempts. Verification locked for ${m} min.`,
      resendEarly: (s: number) => `Cooldown active. Resend in ${s}s.`,
      expiredOrUsed:
        "This code has expired or was already used. Request a new one.",
      latestWins: "A new code was sent. The previous code is no longer valid.",
      suspendedNotice:
        "This account is suspended. Contact support for assistance.",
      noAccount:
        "No doctor, lab or chemist account was found for this number. Register your practice or business to get started.",
      networkError: "Could not reach the server. Check your connection.",
      smsFailed: "We could not send the code. Try again in a moment.",
      demoOtp: (code: string) => `Demo OTP: ${code}`,
      verifiedTitle: "Identity verified",
      verifiedBody: "Your practice is verified and your console is ready.",
      // #566: the terminal step's own submit label. The handoff is up and the
      // sign-in submit control is gone by then, so this only ever names the
      // state - it must never read as "request a code" again.
      verifiedSubmit: "Continue",
    },
    pending: {
      badge: "Under Verification",
      headerTitle: "Application status",
      title: "Your application is being verified",
      submittedLabel: "Submitted",
      applicationLabel: "Application",
      verifyingLabel: "Being verified",
      windowLabel: "Expected review window",
      detailPlaceholder: "Shown once staff accounts go live (Phase 5)",
      windowValue: "Within 48 hours",
      infoBanner:
        "You are not listed publicly until activated. We will call or message you if anything more is needed.",
      helpCta: "Help: contact the CareSetu team",
      loadError:
        "Could not load your application status. Please check your connection and try again.",
    },
    rejected: {
      badge: "Rejected",
      headerTitle: "Application status",
      title: "We could not verify your application",
      reasonHeading: "Reason:",
      reasonPlaceholder:
        "The specific reason appears here once operator review goes live (Phase 5).",
      fixNote:
        "Fix the issue and resubmit - your corrected upload goes straight back into verification; you do not start over.",
      resubmitCta: "Re-upload and resubmit",
      resubmitStubNotice:
        "Resubmission opens with Phase 5 - nothing was resubmitted just now.",
      helpCta: "Help: contact the CareSetu team",
      loadError:
        "Could not load your rejection details. Please check your connection and try again.",
      appealProcessing: "Submitting your appeal...",
      appealSuccess:
        "Appeal submitted. You are back in the verification queue.",
    },
    picker: {
      title: "Choose a role to continue",
      sub: "This account holds more than one staff role. Pick which console to open - you can switch later from the top bar.",
      doctorDesc: "Queue, cases, patients, profile",
      partnerDesc: "Orders, history, settlements, profile",
      operatorDesc: "Verifications, disputes, audit",
    },

    // register.* surface - PHASE-2.6 T11 (#202): the four-step provider
    // application wizard (/staff/register, blueprint §4.3). Client-side
    // validation mirrors the planned Phase 5 field schemas (prototype
    // provider-register.html is the binding copy spec); error keys below are
    // produced by providerRegisterState.ts and resolved with t.errors[key].
    register: {
      subtitle:
        "Apply now - our team verifies every credential before you are listed.",
      stepperLabel: "Registration steps",
      steps: [
        "Account basics",
        "Identity",
        "Credentials",
        "Review & declarations",
      ],
      typeBadge: {
        doctor: "Doctor application",
        lab: "Lab application",
        chemist: "Chemist application",
      },
      typeLabels: { doctor: "Doctor", lab: "Lab", chemist: "Chemist" },
      back: "Back",
      continueCta: "Continue",
      submitApplication: "Submit application",
      // FEAT-014 T08 (#468): phone-confirmation step between review and
      // landing - the OTP card itself reuses the staffAuth.login copy; only
      // the step's own heading and submit label live here.
      phoneConfirm: {
        title: "Confirm your phone",
        helper:
          "We texted a 6-digit code to this number to keep your application tied to a phone you control. Enter the code to finish - your details are saved.",
        confirmCode: "Confirm code",
      },
      summaryTitle: (n: number) =>
        `${n} ${
          n === 1 ? "field needs" : "fields need"
        } attention before you continue.`,
      accountTitle: "Account basics",
      identityTitleDoctor: "Professional identity",
      identityTitlePartner: "Business identity",
      credentialsTitle: "Credentials upload",
      credentialsNote:
        "Photos or PDFs. Files are checked by our team; nothing is listed publicly until activation.",
      reviewTitle: "Review & declarations",
      fields: {
        fullName: "Full name",
        fullNamePlaceholder: "e.g. Dr. Asha Kumar",
        email: "Email",
        emailPlaceholder: "you@example.com",
        password: "Password",
        passwordHelp:
          "Strength: use 12+ characters with a number and a symbol.",
        mobile: "Mobile for alerts",
        mobilePlaceholder: "10-digit mobile number",
        degreeName: "Name as per degree",
        degreeNamePlaceholder: "Exactly as printed on your certificate",
        council: "State medical council",
        councilPlaceholder: "Select your council",
        city: "City",
        cityPlaceholder: "e.g. Daltonganj",
        languages: "Languages spoken",
        languagesPlaceholder: "e.g. Hindi, English",
        businessName: "Business name",
        address: "Address",
        serviceArea: "Service area",
        serviceAreaPlaceholder: "e.g. Daltonganj + 15 km",
        ownerContact: "Owner contact",
      },
      optionalSuffix: "(optional)",
      mobilePrefix: "+91",
      councils: [
        "Jharkhand State Medical Council",
        "Bihar State Medical Council",
        "Other",
      ],
      slots: {
        councilCert: {
          label: "State medical council registration certificate",
          hint: "Upload photo/PDF",
        },
        degrees: {
          label: "Degree certificates (MBBS / MD)",
          hint: "Upload photo/PDF",
        },
        photoId: { label: "Government photo ID", hint: "Aadhaar / PAN / DL" },
        businessReg: {
          label: "Business registration",
          hint: "GST / trade license",
        },
        accreditations: { label: "Accreditations", hint: "NABL / ISO if held" },
        kyc: { label: "Owner KYC", hint: "Government photo ID" },
        drugLicense: {
          label: "Drug license (Form 20/21)",
          hint: "Upload photo/PDF",
        },
        shopLicense: { label: "Shop license", hint: "Municipal trade license" },
      },
      uploadPrompt: "Upload photo/PDF",
      removeFile: "Remove",
      review: {
        applicant: "Applicant",
        email: "Email",
        mobile: "Mobile for alerts",
        notProvided: "Not provided",
        type: "Type",
        credentialsAttached: "Credentials attached",
        fileCount: (n: number) => `${n} ${n === 1 ? "file" : "files"}`,
        noFile: "Nothing attached yet",
      },
      declarations: {
        truth: "I declare the information and documents provided are true.",
        consent: "I consent to credential verification by CareSetu.",
        terms: "I accept the Terms of Service.",
      },
      errors: {
        fullNameRequired: "Enter your full name.",
        emailInvalid: "Enter a valid email address.",
        passwordWeak:
          "Use at least 12 characters including a number and a symbol.",
        mobileRequired: "Enter your mobile number.",
        mobileInvalid: "Enter a valid 10-digit Indian mobile number.",
        degreeNameRequired: "Enter your name as per degree.",
        councilRequired: "Select your state medical council.",
        cityRequired: "Enter your city.",
        languagesRequired: "Enter the languages you speak with patients.",
        businessNameRequired: "Enter the business name.",
        addressRequired: "Enter the business address.",
        serviceAreaRequired: "Enter the area you serve.",
        ownerContactInvalid:
          "Enter the owner's valid 10-digit Indian mobile number.",
        uploadRequired: "Attach this document to continue.",
        uploadWrongType:
          "Only photos (JPEG, PNG, WebP) or PDF files work here.",
        uploadTooLarge: "Files must be 10 MB or smaller.",
        declarationRequired: "Tick this declaration to continue.",
      },
      phase5Notice:
        "Submission is not connected yet: applications arrive in Phase 5. Nothing was sent or saved just now.",
      submitting: "Submitting...",
      traceWithId: (traceId: string) => `Trace: ${traceId}`,
      errorsSubmitLocationRequired:
        "Unable to determine your location. Please allow location access and try again.",
      errorsSubmitUnexpected: "An unexpected error occurred. Please try again.",
    },
  },

  // doctor.* surface - PROGRAM landing inside the doctor console (Phase 5,
  // doctor landing page, P5 FE #291). String keys come from the binding
  // doctor-resolved view; bilingual parity is compile-time enforced via
  // Dictionary = typeof en.
  doctor: {
    welcome: (displayName: string) => `Welcome, ${displayName}`,
    doctorLabel: "Doctor",
    doctorWithPhone: (phone: string) => `Doctor (${phone})`,
    workspaceActive: "Your doctor workspace is active.",
    statusHeading: "Status",
    profileActive:
      "Your profile is active and verified. You can begin accepting consultations.",
    nextStepsHeading: "Next Steps",
    nextSteps: [
      "- Complete your professional profile (coming soon)",
      "- Browse the patient directory (Phase 6)",
      "- Start a consultation from a patient record",
    ],
  },

  // home.* surface - the resolved public homepage's copy (PHASE-2.6 T09,
  // #200), carried over verbatim from the finalized PROTO-PHASE-2.6 view
  // home-resolved.html; the specialty-chip labels the prototype left
  // untranslated get their Hindi strings here so REQ-006 parity holds for
  // every rendered node. Copy rules baked in: categories are marketing
  // navigation over specialties - no disease-based program promises (G1);
  // the directory empty state stays honest about launch status (G2).
  home: {
    nav: {
      doctors: "Doctors",
      labs: "Labs",
      chemists: "Chemists",
    },
    authButton: {
      login: "Login",
      dashboard: "Dashboard",
    },
    hero: {
      h1: "Find trusted doctors, labs and chemists near you",
      sub: "Book visits, share reports and keep every record in one place - shared only with your consent.",
      typeLabel: "Provider type",
      typeDoctor: "Doctor",
      typeLab: "Lab",
      typeChemist: "Chemist",
      searchPlaceholder: "Search by name, specialty or test",
      locationLabel: "Location",
      cta: "Search",
      getStarted: "Get started",
    },
    chips: {
      title: "Common needs",
      generalPhysician: "General Physician",
      pediatrician: "Pediatrician",
      gynecologist: "Gynecologist",
      dentist: "Dentist",
      bloodTest: "Blood test",
      xRay: "X-ray",
      fullBodyCheckup: "Full body checkup",
      medicineDelivery: "Medicine delivery",
    },
    tiles: {
      title: "Browse by category",
      doctorsSub: "GP, Pediatrician, Gynecologist, Dentist",
      labsSub: "Blood tests, X-ray, full body checkup",
      chemistsSub: "Medicine delivery with e-prescription",
    },
    featured: {
      title: "Featured doctors",
      viewAll: "View all doctors",
      verified: "Verified",
      emptyTitle: "Directory launching soon in Daltonganj",
      emptyBody:
        "We verify every provider before listing. No doctors are shown until their credentials clear verification.",
      emptyCta: "Get started as a patient",
    },
    how: {
      title: "How CareSetu works",
      s1t: "Find a provider",
      s1b: "Search verified doctors, labs and chemists near you.",
      s2t: "Share symptoms by voice",
      s2b: "AI drafts a pre-summary - your doctor always reviews it before anything moves forward.",
      s3t: "Everything stays in one place",
      s3b: "Prescriptions, reports and records live in your health record, shared only with your consent.",
    },
    trust: {
      t1: "Credentials verified before listing",
      t2: "Nothing is shared without your consent",
      t3: "Your records, your control - revocable anytime",
      privacy: "Privacy & terms",
    },
    providers: {
      title: "Are you a provider?",
      sub: "Register now - our team verifies before you are listed.",
      doctorT: "Are you a doctor?",
      doctorB: "Reach patients looking for verified care in your city.",
      labT: "Run a lab?",
      labB: "Receive booked-test orders and file reports digitally.",
      chemistT: "Own a chemist shop?",
      chemistB: "Fill approved e-prescriptions and grow your counter.",
      register: "Register",
    },
    finalCta: {
      title: "Start with your health record",
      sub: "One free account keeps your records, bookings and orders together.",
    },
    footer: {
      patients: "Patients",
      providersCol: "Providers",
      companyLegal: "Company & legal",
      findDoctors: "Find doctors",
      findLabs: "Find labs",
      findChemists: "Find chemists",
      howItWorks: "How it works",
      regDoctor: "Register as doctor",
      regLab: "Register as lab",
      regChemist: "Register as chemist",
      staffLogin: "Staff login",
      about: "About",
      privacy: "Privacy",
      terms: "Terms",
      contact: "Contact",
      meta: "\u00a9 CareSetu - serving Daltonganj & peri-urban areas",
      operatorConsole: "Operator console",
    },
  },

  // patientHome.* surface - PHASE-2.7 T1 (#499), the reworked patient home
  // (PROTO-2.7 binding: a full-width greeting strip above a responsive
  // two-column feed). The greeting is i18n-driven: the saved first name is
  // interpolated when one exists, the generic greeting stands in when none is
  // saved. Feed-card copy lands with the sibling PROTO-2.7 tickets.
  //
  // #500: the slim one-line profile banner lives here too (PROTO-2.7
  // `profile.banner` copy, re-keyed to the home surface) - a dismissible
  // nudge, never a blocking gate, gone entirely once name/age/gender exist.
  patientHome: {
    welcome: (firstName: string) => `Namaste, ${firstName}`,
    welcomeGuest: "Namaste",
    greetSub: "Good to see you. What would you like to do today?",
    banner: "Add your name, age & gender to start a visit",
    bannerCta: "Complete profile",
    bannerDismiss: "Dismiss profile reminder",
  },

  // loc.* surface - #501, the patient location chip and its single-city picker
  // sheet (PROTO-2.7 binding, shell-light.html #location-sheet). The picker
  // lists only the launch beachhead today, explicitly marked single-city with a
  // coming-soon note for future cities; choosing it persists the area through
  // the profile draft/save flow (REQ-008 single-service-area). `cities` is keyed
  // by the service-area enum id (lib/location/serviceArea) so the enum stays the
  // single source of truth and each id carries its localized label.
  loc: {
    aria: "Change my location",
    title: "My location",
    desc: "Used to find care near you and saved to your profile. Find Care and medicine checkout respect it.",
    cities: {
      Daltonganj: "Daltonganj",
    },
    citySub: "Daltonganj + peri-urban",
    more: "More cities coming soon",
    apply: "Apply location",
  },

  // search.* surface - #502, the home search card (PROTO-2.7 binding,
  // shell-light.html `.search-card`): the Doctor / Lab / Chemist scope pills
  // reuse the provider-type tri-state as display-driven scope, and the search
  // bar routes to scoped Find Care (`/patient/find?type=...&q=...`). The
  // directory is the single filter source - this card never searches itself.
  search: {
    scopeAria: "Search scope",
    doctor: "Doctor",
    lab: "Lab",
    chemist: "Chemist",
    // #509: distinct from `aria` - the placeholder hints at what can be
    // searched ("Doctor, lab, test or medicine") while the label announces the
    // screen's search purpose ("Search care near you"). Both kept EN/HI.
    placeholder: "Doctor, lab, test or medicine",
    aria: "Search care near you",
    go: "Search",
    seeAll: "See all",
  },

  // rec.* surface - #503, the "Recommended near you" rail (PROTO-2.7 binding,
  // shell-light.html `.rec`). A sibling of the home search card: fetches the
  // active scope's verified directory entries so patients can jump straight to
  // verified care near them. Card-internal labels (Verified, distance,
  // specialty/type words) reuse the directory.* card language - this surface
  // only owns the rail's own heading and states.
  rec: {
    title: "Recommended near you",
    aria: "Recommended care near you",
    loading: "Finding care near you...",
    emptyTitle: "No verified providers nearby yet",
    emptyBody: "As providers in Daltonganj get verified, they appear here.",
    providerFallback: "CareSetu provider",
  },

  // services.* surface - #504, the fixed 4-tile services grid (PROTO-2.7
  // binding, shell-light.html `.services-grid`): Consult a doctor, Book a lab
  // test, Start visit (the accent tile) and Order medicine - in that fixed
  // order. Order medicine renders marked Soon and never navigates (`soon`);
  // the other three tiles are one-tap actions. The consult and lab tiles reuse
  // the scoped Find Care destinations the home search card (#502) owns; Start
  // visit points at the live intake start (the center accent of the patient
  // tab bar).
  services: {
    title: "Services",
    doctor: "Consult a doctor",
    lab: "Book a lab test",
    chemist: "Order medicine",
    start: "Start visit",
    soon: "Soon",
  },

  // actions.* surface - #505, the home "Action required" card (PROTO-2.7
  // binding, shell-light.html `actions.*`). Hidden entirely when nothing is
  // pending. Today the only source is pending patient-consent requests
  // (consent log filtered to status "requested"): each row names the requester
  // and scope, and Allow / Not now answer it through the existing grant-
  // requested and decline flows. Rx substitute/refund and booking
  // confirmations are future sources and are deliberately not stubbed.
  actions: {
    title: "Action required",
    consentBadge: "Consent",
    consentRequest: (name: string, scope: string) =>
      `${name} requested access to your ${scope}.`,
    allow: "Allow",
    deny: "Not now",
    actionFailed: "Couldn't update. Please try again.",
  },

  // recent.* surface - #506, the home "Recent activity" card (PROTO-2.7
  // binding, shell-light.html `recent.*`). Shows the top few record-timeline
  // events (consultations, prescriptions, lab results, metric logs) rendered
  // through the shared My Record describe/format helper, so the card only owns
  // its heading, the View all destination copy and the fresh-record empty
  // state. Per-type badge labels are reused from record.badge, never re-keyed.
  recent: {
    title: "Recent activity",
    all: "View all",
    loading: "Loading your recent activity...",
    empty: "Your activity will appear here",
    emptyBody:
      "After your first consult, completed visits, reports and logs show up here. Find a doctor below to get started.",
  },

  // health.* surface - #507, the home "Health snapshot" right-rail card
  // (PROTO-2.7 binding, shell-light.html `health.*`). Honest by construction:
  // the last logged metric and latest report are derived from the record
  // timeline when they exist; when either is absent the card says Soon instead
  // of inventing values. The binding's demo-only KPI copy (bpValue, bpWhen,
  // report1 etc.) is deliberately never shipped - only derived facts render
  // numbers and dates here.
  health: {
    title: "Health snapshot",
    metricLabel: "Last logged metric",
    trackSoon: "Health tracking",
    teaser: "Track your blood pressure & sugar",
    teaserBody:
      "Daily logging and trends arrive with Health tracking. Your data stays under your consent control.",
    reportsTitle: "Reports",
    reportSoon: "Lab reports appear here once available",
    soon: "Soon",
    loading: "Loading your health snapshot...",
  },

  // directory.* surface - PHASE-6 T05a (#317), the public /directory browse
  // page (blueprint §3.1 row 2 look, PROTO-PHASE-6 finalized views are the
  // visual binding). Copy rules baked in: the location indicator is the fixed
  // launch beachhead (REQ-008) - never promise multi-city search; filters are
  // provider type + doctor specialty (closed pick-list), never disease
  // browsing (G1); the wider-area fallback labels results honestly "outside
  // your area" with every other filter preserved (glossary).
  directory: {
    heading: {
      all: "Find verified care near you",
      doctor: "Find doctors near you",
      lab: "Find labs near you",
      chemist: "Find chemists near you",
    },
    subtitle:
      "Only activated providers with valid credentials are listed, sorted by distance.",
    searchLabel: "Search providers",
    searchPlaceholder: "Search by name or specialty",
    searchCta: "Search",
    filtersLabel: "Filter by provider type and specialty",
    typeAll: "All",
    typeDoctor: "Doctors",
    typeLab: "Labs",
    typeChemist: "Chemists",
    verified: "Verified",
    locationDaltonganj: "Daltonganj",
    distanceKm: (km: string) => `${km} km`,
    resultsCount: (n: number) =>
      `${n} ${n === 1 ? "provider" : "providers"} found`,
    loading: "Searching providers...",
    emptyTitle: "No providers found for this search",
    emptyBody: "Try broadening your search or check nearby areas.",
    clearSearch: "Clear search",
    outsideAreaLabel: "Showing providers outside your area",
    outsideAreaBody:
      "Nothing matched within your area with the filters you chose, so here are the nearest available providers. Your filters are kept.",
    errorTitle: "We could not load the directory",
    errorBody: "Check your connection and try again.",
    retry: "Try again",
  },

  // providerProfile.* surface - PHASE-6 T06 (#312): the public provider
  // profile at /providers/:id (blueprint §3.1 row 5, PROTO-PHASE-6
  // doctor-profile.html / partner-profile.html as the visual binding). Shows
  // only the verified-safe fields the profile API returns - name, partner
  // type, doctor specialty, service area, the verified indicator and the
  // verified credential type + expiry labels. `provider` is the display word
  // legal in this route's copy; `partner` stays the domain word in data.
  providerProfile: {
    verifiedByCareSetu: "Verified by CareSetu",
    verified: "Verified",
    active: "Active",
    credentialsHeading: "Credentials",
    credentialsAndLicensesHeading: "Credentials & licenses",
    practiceDetailsHeading: "Practice details",
    detailsHeading: "Details",
    typeLabel: "Type",
    // #619: the DECLARED band - what the provider says about itself, as opposed
    // to the verified band above, which is what the platform checked. The copy has
    // to make that split legible in words, because the section's dashed edge only
    // makes it legible in shape: a patient must not have to infer which half of
    // the page we are standing behind.
    declaredHeading: "Declared by the provider",
    declaredNote:
      "The provider's own details. CareSetu has not checked them - only the credentials above are verified.",
    declaredPracticeHeading: "Clinic",
    declaredAddressHeading: "Address",
    declaredConsultingHeading: "Consulting",
    declaredAboutHeading: "About",
    clinicNameLabel: "Clinic name",
    specialtiesLabel: "Specialties",
    languagesLabel: "Languages",
    consultingDaysLabel: "Consulting days",
    consultingHoursLabel: "Consulting hours",
    // The address parts are NOT re-declared here. `doctorProfile` already owns a
    // label for each of the same five fields - the same form the doctor fills in,
    // for the same fact - and a second set of Hindi words for "Locality" would be
    // a second place to reword it and a second place to get it wrong. The band
    // reads those maps. The one exception is the landmark: the editor's copy says
    // "optional" because that is an instruction to the doctor filling a form, and
    // on a patient-facing page a landmark they saved is not optional - so that
    // word is ours and only ours.
    declaredLandmarkLabel: "Landmark",
    yearsOfExperience: (years: number) =>
      years === 1 ? "1 year of experience" : `${years} years of experience`,
    experienceLabel: "Experience",
    expiresOn: (date: string) => `Expires ${date}`,
    credentialTypes: {
      medical_registration: "Medical registration",
      qualification_certificate: "Qualification certificate",
      lab_license: "Lab license",
      accreditation: "Accreditation",
      drug_license: "Drug license",
      pharmacist_registration: "Pharmacist registration",
    },
    typeDoctor: "Doctor",
    typeLab: "Laboratory",
    typeChemist: "Chemist",
    breadcrumbDirectory: "Directory",
    loadingProfile: "Loading profile",
    comingSoon: "Coming soon",
    comingSoonBody: "Booking and ordering will be available in a future phase.",
    notFoundTitle: "Provider not found",
    notFoundBody:
      "This provider is either not listed in the directory or is no longer active. Only activated and verified providers appear here.",
    notFoundCta: "Browse the directory",
    loadError: "We could not load this provider profile.",
    retry: "Try again",
  },

  // consent.* surface - PHASE-2.6 T12 (#203): the reusable consent-moment
  // bottom sheet (blueprint §5.10, finalized PROTO-PHASE-2.6 view
  // consent-sheet.html). Labels/buttons are component-owned; the per-request
  // content (requester, scope, validity) is host-supplied - the demo keys
  // under `demo` carry it for the patient-surface demo integration point.
  // Copy rules baked in: scope is always specific, never blanket wording;
  // denial explains plainly what stays blocked and never nags.
  consent: {
    title: "Sharing permission",
    whoLabel: "Who is asking",
    whatLabel: "What they will see",
    howLongLabel: "For how long",
    verifiedBadge: "Verified",
    allow: "Allow",
    deny: "Not now",
    logLink: "See all permissions",
    grantedNote: "Allowed - recorded in your consent log.",
    deniedNote:
      "No problem. Without permission the lab cannot attach your history to this booking - you can still book, just without record sharing.",
    demo: {
      badge: "Demo care action",
      cardTitle: "Book a lab test",
      cardBody:
        "This booking wants to attach your recent history so the doctor has context. Nothing is shared unless you allow it.",
      cta: "Continue booking",
      requesterName: "Sahyog Path Lab",
      requesterContext: "via your booking · Dr. A. Kumar reference",
      scope: "Your prescriptions from the last 3 months",
      validity:
        "This one booking only. You can revoke anytime in My Record → Consent log.",
      allowedProceed: "Your booking continues - your history is attached.",
      standingDenial: "You chose Not now earlier - nothing has been shared.",
    },
  },

  // profile.* surface - PHASE-2.6 T13 (#204): the first-login profile-
  // completion wizard (blueprint §5.9, finalized PROTO-PHASE-2.6 view
  // profile-completion.html is the binding copy spec). Step/copy keys carry
  // the prototype's pc.* strings; nudge/gate/demo keys extend the §5.9 rules
  // (browse never gated; intake/booking gated on basics; medicine-delivery
  // checkout gated on area; skips resurface as gentle Home nudges - never
  // modals).
  profile: {
    title: "Welcome! Set up your profile",
    sub: "Three quick steps. You can skip the optional ones and finish later.",
    pageTitle: "Complete your profile",
    steps: ["Required", "Optional", "Optional"],
    s1: "About you",
    s2: "Health tracking (optional)",
    s2sub:
      "Turn on daily logging for blood pressure or sugar - we will remind you gently.",
    s3: "Contact & photo (optional)",
    name: "Full name",
    namePlaceholder: "e.g. Asha Devi",
    age: "Age",
    agePlaceholder: "Years",
    gender: "Gender",
    genderPlaceholder: "Select",
    genders: { female: "Female", male: "Male", other: "Other" },
    langLabel: "Language preference",
    bp: "Blood pressure",
    sugar: "Blood sugar",
    photo: "Profile photo",
    photoPrompt: "Upload photo",
    area: "Area / address",
    areaPlaceholder: "Ward, mohalla, landmark",
    ec: "Emergency contact",
    ecPlaceholder: "+91",
    skip: "Skip for now",
    continueCta: "Continue",
    finish: "Finish",
    meterLabel: "Profile complete",
    errors: {
      nameRequired: "Enter your full name.",
      ageRequired: "Enter your age.",
      ageInvalid: "Enter age as a whole number between 1 and 120.",
      genderRequired: "Select your gender.",
    },
    nudges: {
      basicsTitle: "Add your name to start a visit",
      basicsBody: "Care actions need a named record - it takes one minute.",
      trackingTitle: "Turn on health tracking",
      trackingBody:
        "Daily BP or sugar logging switches on gentle due-card reminders.",
      photoTitle: "Add a profile photo",
      photoBody: "Helps providers confirm they are treating the right person.",
      areaTitle: "Add your area for medicine delivery",
      areaBody: "Delivery checkout needs an area or address to ship to.",
      emergencyTitle: "Add an emergency contact",
      emergencyBody:
        "One phone number we can reach if something urgent happens.",
      dismiss: "Dismiss",
      completeCta: "Complete profile",
    },
    gate: {
      basicsExplain:
        "A named record (name, age, gender) is required for care actions - add it here to continue.",
      areaExplain:
        "Medicine delivery needs your area or address - add it here to continue.",
    },
    // save.* - PHASE-8.1 T2 (#488): Finish persistence state surfaced by the
    // wizard hosts (complete page + inline gate) while PUT /v1/me/profile runs.
    save: {
      saving: "Saving your profile...",
      saved: "Profile saved",
      error:
        "We could not save your profile. Please check your connection and try again.",
    },
    // settings.* - Profile & Settings page (#522): the patient account surface
    // for editing identity basics, gated on a complete name/age/gender.
    settings: {
      title: "Profile & Settings",
      sub: "Your name, age, and gender help us keep your care records correct.",
      basics: "Personal details",
      save: "Save changes",
      blocked: "Enter your name, age, and gender to save your profile.",
    },
    demo: {
      badge: "Demo care actions",
      title: "Care-action gating",
      body: "Browsing Find Care and My Record is never gated. Care actions check your profile at the moment you act:",
      intake: "Start visit (intake)",
      booking: "Book appointment",
      checkout: "Medicine delivery - go to checkout",
      proceedNote:
        "This action clears gating - the real intake/booking/checkout flows arrive in their build phases.",
    },
  },

  // profileZones.* - PHASE-8.1 #548: the three-zone patient profile page
  // (US-24/US-25). Identity carries the editable profile fields plus the photo
  // control (upload/preview/remove against the private photo endpoint, #533);
  // HealthBackground is a placeholder zone the next ticket fills; Settings
  // carries notification preferences, the default language, consent-grant
  // management, and the data export/delete leads. A "coming soon" string is
  // used only where the capability genuinely does not exist yet, so the page
  // never promises a control that would do nothing.
  profileZones: {
    identityHeading: "Identity",
    identitySub:
      "How you appear on your care record and to the providers you see",
    photoHeading: "Profile photo",
    photoHelp:
      "JPEG, PNG or WebP, up to 5MB. Shared only with providers you consent with.",
    photoUpload: "Upload photo",
    photoReplace: "Replace photo",
    photoRemove: "Remove photo",
    photoFailed: "We could not update your photo. Please try again.",
    healthHeading: "Health background",
    healthSub:
      "What your providers should know about you before they treat you",
    healthPending:
      "You have not added a health background yet. Add your allergies, conditions and current medicines below.",
    healthLoading: "Loading your health background...",
    healthLoadFailed: "We could not load your health background.",
    healthRetry: "Try again",
    bloodGroupLabel: "Blood group",
    bloodGroupPlaceholder: "For example, B+",
    listHint: "Write one item per line.",
    conditionsLabel: "Conditions",
    conditionsPlaceholder: "For example, Asthma",
    allergiesLabel: "Allergies",
    allergiesPlaceholder: "For example, Penicillin",
    medicationsLabel: "Current medicines",
    medicationsPlaceholder: "For example, Salbutamol inhaler",
    immunizationsLabel: "Immunizations",
    immunizationsPlaceholder: "For example, Tetanus in 2024",
    familyHistoryLabel: "Family history",
    familyHistoryPlaceholder: "For example, Father - diabetes",
    snapshotSave: "Save health background",
    snapshotSaved: "Health background saved.",
    snapshotSaveFailed:
      "We could not save your health background. Please try again.",
    snapshotSharedNote:
      "Your doctors with an active relationship with you can see this health background.",
    metricsHeading: "Height and weight",
    metricsSub: "Your measurements over time, newest first.",
    metricsEmpty: "You have not added any height or weight measurements yet.",
    metricsLoading: "Loading your measurements...",
    metricsLoadFailed: "We could not load your measurements.",
    // The series is a server-paged list; the rest is one tap away rather than
    // silently absent.
    metricsLoadMore: "Show earlier measurements",
    metricsLoadingMore: "Loading earlier measurements...",
    metricsMoreFailed: "We could not load the earlier measurements.",
    heightLabel: "Height (cm)",
    weightLabel: "Weight (kg)",
    // The units stand on their own in a measurement row, where the label is
    // already spoken by the value's own column heading.
    heightUnit: "cm",
    weightUnit: "kg",
    recordedAtLabel: "Measured on",
    metricAdd: "Add measurement",
    metricAdded: "Measurement added.",
    metricAddFailed: "We could not add that measurement. Please try again.",
    metricNotRecorded: "Not recorded",
    metricValueRequired: "Enter a height, a weight, or both.",
    metricValueNotANumber: "Use numbers only, like 170 or 68.5.",
    // The bounds are interpolated from the constants the same form enforces
    // (lib/health-background/form.ts), so a change to what the client accepts
    // cannot leave the message quoting a different range.
    metricHeightRange: (min: number, max: number) =>
      `Enter a height between ${min} and ${max} cm.`,
    metricWeightRange: (min: number, max: number) =>
      `Enter a weight between ${min} and ${max} kg.`,
    metricRecordedAtRequired: "Tell us when this was measured.",
    metricDateInvalid: "That date could not be read. Pick it again.",
    // The one-time first-save confirmation (US-21/US-22/US-23, ADR-0018). Plain
    // language about exactly who gains visibility, what they will see, and how
    // to take it back - never a blanket "your data will be shared" line. The
    // backend stamps this acknowledgment once and never re-asks, so the sheet
    // opens only before that first acknowledged save.
    healthConsentTitle: "Share your health background?",
    healthConsentBody:
      "Saving your health background for the first time makes it visible to the doctors you have an active relationship with. They will see your blood group, conditions, allergies, current medicines, immunizations and family history.",
    healthConsentRecall:
      "You can take back this access at any time from Who can see your records, further down this page.",
    healthConsentConfirm: "Save and share",
    healthConsentCancel: "Not now",
    settingsHeading: "Settings",
    notificationsHeading: "Notifications",
    notificationsHelp:
      "Choose which reminders CareSetu sends you. Arriving with the next release.",
    notificationsSoon: "Coming soon",
    notificationLabels: {
      appointment_reminders: "Appointment reminders",
      prescription_updates: "Prescription updates",
      report_ready: "Reports ready",
      care_messages: "Messages from your provider",
    },
    languageHeading: "Default language",
    languageHelp:
      "The language your care record uses. You can change it in Identity above.",
    consentHeading: "Who can see your records",
    consentSub:
      "Every access you have granted. Revoking one stops future access from that provider.",
    consentEmpty: "You have not shared your records with anyone yet.",
    consentLoading: "Loading your consent grants...",
    consentLoadFailed: "We could not load your consent grants.",
    consentRetry: "Try again",
    consentRevoke: "Revoke access",
    consentRevokeTitle: "Revoke access?",
    consentRevokeBody: (name: string) =>
      `${name} will not be able to see your records from now on. Access already made stays in your access history.`,
    consentRevokeConfirm: "Revoke",
    consentRevokeCancel: "Keep access",
    consentRevokeDone: "Access revoked.",
    consentRevokeFailed: "We could not revoke that access. Please try again.",
    dataHeading: "Your data",
    dataExport: "Download a copy of my data",
    dataExportHelp: "Everything we hold about you, as a file.",
    dataDelete: "Delete my account and data",
    dataDeleteHelp: "Permanently remove your account and care records.",
    dataSoon: "Coming soon",
    scopeLabels: {
      consultations: "Consultations",
      prescriptions: "Prescriptions",
      lab_results: "Lab results",
      metrics: "Metrics",
      health_background: "Health background",
      full_record: "Full record",
    },
    // Shown when the backend returns a scope this build has no label for. The
    // patient must never read a raw snake_case token as though it were a name,
    // and the revoke control stays available regardless: an unlabelled scope is
    // still access they hold and can give back.
    consentScopeOther: "Other parts of your record",
  },

  // nav.* surface - the typed nav-config labels (PHASE-2.6 T06, #197).
  // One entry per NavItemDef.labelKey across all four role configs; the
  // bottom tabs / top-nav / sidebar all render through this section.
  nav: {
    home: "Home",
    find: "Find Care",
    start: "Start",
    record: "My Record",
    inbox: "Inbox",
    bookings: "Bookings & Orders",
    profileSettings: "Profile & Settings",
    more: "More",
    // #525/#526: the account cluster's sign-out row in both the mobile More
    // sheet and the desktop dropdown. Spell "Log out" as two words per spec
    // #520 vocabulary.
    logOut: "Log out",
    // #604: the doctor landing area is the doctor's Dashboard, not a "Queue".
    // Value-only change on this one key: NavItemDef.key stays "queue" and
    // href stays /doctor, so the route and every test id derived from that key
    // (nav-queue, tab-queue, more-queue) are untouched, while the sidebar and
    // the phone tab bar - both fed from NAV_CONFIG.doctor and both resolving
    // this same labelKey - move together and cannot drift.
    queue: "Dashboard",
    cases: "Cases",
    patients: "Patients",
    orders: "Orders",
    history: "History",
    settlements: "Settlements",
    profile: "Profile",
    verifications: "Verifications",
    disputes: "Disputes",
    audit: "Audit",
    // #538: section-group labels for the redesigned full-shell sidebar. Nav
    // items declare a group via NavItemDef.group; the sidebar composes ordered
    // labeled groups from these keys.
    sections: {
      work: "Work",
      account: "Account",
    },
    // #574: the sidebar's collapse control. Two flat keys, not one conditional
    // function - this namespace carries plain strings only, like `logOut`,
    // `more` and `sections` above. Each names the ACTION, so the polarity
    // flips with the rail: the collapsed rail's control says "expand".
    collapseSidebar: "Collapse sidebar",
    expandSidebar: "Expand sidebar",
  },

  // accountMenu.* surface - #526: chrome copy for the desktop account
  // dropdown. Model note (spec #520): "account menu" is UI chrome terminology
  // only, not a domain entity; these keys are display chrome, never shared
  // with the nav-config surface (which indexes `nav.*` and carries one entry
  // per NavItemDef.labelKey - no functions allowed there).
  accountMenu: {
    trigger: "Account menu",
    completeProfile: "Complete your profile",
    // #604: the popup's own Profile row label. It used to read nav.profile -
    // the sidebar's label key - so the popup row and the sidebar entry could
    // only ever say the same thing. This namespace owns it instead, so the
    // popup can say what it means (Profile & Settings) and the sidebar label
    // for the profile entry stays exactly as it was.
    profileSettings: "Profile & Settings",
    switchRole: (roleLabel: string) => `Switch to ${roleLabel}`,
  },

  // record.* surface - PHASE-3 T7 (#216): the My Record timeline screen
  // (blueprint §5.5, binding prototype record.html). Filter naming follows
  // the ratified review outcome: "Consultations" everywhere incl. Hindi
  // परामर्श - consultation wording, never physical-visit.
  // PROTO-3.1 (#511): heading and snapshot/rail copy for the two-zone
  // redesign; month names come from Intl, never from these dictionaries.
  record: {
    title: "My Health Record",
    description:
      "Your health story in one place - consultations, prescriptions, lab results and daily metrics.",
    summaryLabel: "At a glance",
    today: "Today",
    yesterday: "Yesterday",
    snapshot: {
      all: "Everything",
    },
    snapshotIssued: (count: number) => `${count} issued`,
    snapshotFlagged: (count: number) => `${count} flagged`,
    outOfRange: {
      above: "above usual range",
      below: "below usual range",
      footnote: (count: number) =>
        `${count} values outside your usual range - open the report for details.`,
    },
    accessAccordionHint:
      "Expand to see the latest 5 accesses - the full audit lives in your consent log.",
    openConsentLog: "Open consent log",
    filterGroupLabel: "Filter record entries",
    moreMenuLabel: "More filters",
    filter: {
      all: "All",
      consultation: "Consultations",
      prescription: "Prescriptions",
      labReport: "Lab results",
      metric: "Metrics",
      more: "More",
    },
    badge: {
      consultation: "Consultation",
      prescription: "Prescription",
      labReport: "Lab result",
      metric: "Metric",
      settlement: "Settlement",
      issued: "Issued",
      active: "Active",
      delivered: "Delivered",
    },
    filedFromBooking: "filed from booking",
    // #515: professional prescription card lines - the attribution reads
    // "issued by <doctor>" when the payload names one and falls back to
    // neutral copy when `attributed_doctor_name` is null, so the card never
    // invents a doctor.
    issuedBy: (doctor: string) => `issued by ${doctor}`,
    issuedByNeutral: "issued by your care team",
    prescribedBy: "Prescribed by",
    moreItems: (count: number) => `+${count} more`,
    empty: {
      title: "No entries yet",
      body: "Your consultations, prescriptions, lab results and metrics appear here as your care happens.",
    },
    loadError: "Could not load your record.",
    accessHistory: {
      heading: "Who accessed my record",
      loadError: "Could not load access history.",
      emptyTitle: "No access yet",
      emptyBody:
        "When a doctor, lab or chemist views your record, it appears here.",
      scopePrefix: "Consent scope: ",
      deniedLabel: "Denied",
      deniedReasonPrefix: "Reason: ",
    },
    detail: {
      loadError: "Could not load this entry.",
      notFound: "Entry not found.",
      filedOn: "Filed",
      bookingRef: "booking",
      sourceHeading: "Source",
      verified: "Verified",
      consentHeading: "Consent reference",
      consentLine: (lineageRef: string, version: number, date: string) =>
        `Shared to your record under consent #${lineageRef} v${version}, granted ${date}.`,
      consentLink: "See this permission in your consent log",
      resultsHeading: "Results",
      resultsThTest: "Test",
      resultsThValue: "Value",
      resultsThRange: "Usual range",
      resultsThStatus: "Status",
      resultsNote:
        "Values are shown exactly as the lab filed them. Your doctor reads them in full context - the app does not interpret results.",
      resultsStatusInRange: "In range",
      resultsStatusBelowRange: "Below range",
      resultsStatusAboveRange: "Above range",
      egressHeading: "Who has seen this entry",
      shareEntry: "Share this entry",
      downloadPdf: "Download PDF",
    },
  },
  consentLog: {
    title: "Consent log",
    description:
      "Every permission you have given or taken back - each with its own receipt.",
    pendingHeading: "Needs your answer",
    historyHeading: "Earlier permissions",
    badge: {
      requested: "Requested",
      active: "Active",
      revoked: "Revoked",
    },
    viewReceipt: "View receipt",
    metaRequested: "requested",
    metaGranted: "granted",
    receiptRequested: "Requested on {date}.",
    receiptGranted: "Granted on {date}.",
    receiptRevoked: "Revoked on {date} - any further use stopped immediately.",
    allow: "Allow",
    decline: "Not now",
    revoke: "Revoke",
    stopForward:
      "Revocation does not erase what was already seen. This partner retains any data they received under this permission.",
    revokeConfirm: {
      title: "Take back this permission?",
      body: "Sharing stops immediately - the partner loses access going forward. What was already seen or sent stays with them as per their retention duty. You can always allow a similar permission again later (it becomes a new version).",
      confirm: "Yes, take it back",
      cancel: "Keep it",
      done: "Permission taken back - future sharing stopped.",
    },
    egress: {
      heading: "What has left your record",
      description:
        "Every time something from your record was read or sent, it is written here - who, when, under which permission.",
      th: {
        when: "When",
        what: "What",
        to: "To whom",
        via: "Under which permission",
      },
    },
    empty: {
      title: "No consent history yet",
      body: "Consent interactions will appear here as you share or restrict access to your record.",
    },
    loadError: "Could not load your consent log.",
  },

  // intake.* surface - MOD-005 symptom intake (PHASE-7 T15, #359): the
  // intake-start mode chooser (blueprint §5.4, finalized PROTO-PHASE-7/8
  // intake-start.html is the binding copy spec). Two oversized first-class
  // inputs - voice is default-highlighted (recommended, never forced) and
  // text is equally first-class (REQ-007 Rule 2). ADR-0001 honesty: the
  // chooser never markets an AI diagnosis.
  intake: {
    breadcrumb: "Start visit",
    title: "Tell us what's bothering you",
    reassure:
      "No forms, no typing. This helps your doctor understand you faster.",
    modeVoice: "Speak",
    modeVoiceSub: "Record in Hindi or English",
    modeText: "Type",
    modeTextSub: "Type your symptoms",

    // voice.- recording surface (PHASE-7 T16, #360): the voice recorder page
    // (blueprint §5.4, finalized PROTO-PHASE-7/8 intake-voice.html is the
    // binding copy spec). A large always-visible mic target, live duration
    // counter capped at 180s, playback + re-record before submit, at most 3
    // voice attempts before the patient types instead, and a plain-language
    // re-record-or-type prompt on short or unclear audio (FEAT-006 scenario
    // 2) - never a silent proceed. Submit uses an in-button Structuring
    // pending state per §9.1; uploads auto-retry ×3 with backoff (§5.2).
    voice: {
      title: "Record your symptoms",
      breadcrumb: "Voice intake",
      reassure: "Just speak naturally - Hindi or English, both are fine.",
      statusIdle: "Tap the mic and describe what's bothering you",
      statusRecording: "Recording… tap to stop",
      statusPaused: "Paused - tap to continue",
      statusPreview: "Preview your recording",
      statusPending: "Structuring… please wait",
      statusDone: "Recording captured",
      statusPoor: "We couldn't hear clearly",
      pause: "Pause",
      resume: "Resume",
      stop: "Stop",
      play: "Play preview",
      stopPreview: "Stop preview",
      recordAgain: "Record again",
      submit: "Submit",
      submitting: "Structuring…",
      poorTitle: "We couldn't hear that clearly",
      poorBody:
        "We couldn't hear clearly. Please re-record or switch to typing.",
      poorRetry: "Try again",
      poorType: "Type instead",
      attemptsExhausted:
        "You've used all 3 voice attempts. Please type your symptoms instead.",
      doneBody: "Taken. We're preparing your pre-summary.",
      next: "See your pre-summary",
      uploadErrorTitle: "We couldn't send your recording",
      uploadErrorBody:
        "Your recording is safe. Check your connection and try again.",
      micUnavailableTitle: "We couldn't reach your microphone",
      micUnavailableBody:
        "Check that microphone access is allowed, then try again.",
    },

    // text- intake surface (PHASE-7 T17, #361): the text form (blueprint §5.4,
    // finalized PROTO-PHASE-7/8 intake-text.html is the binding copy spec). A
    // prominent large textarea capped at 2000 chars in-page (server caps too,
    // T07/T12) with a bilingual hint - Hindi and English both accepted. The
    // optional voice-note attach is a doctor-only audio artifact: stored for
    // the doctor to listen to, never fed to the structuring pipeline, and
    // strictly non-blocking (the note is never required and never blocks the
    // text). Submit shows the same in-button Structuring pending state per
    // §9.1 (never a full-page spinner), then advances to the pre-summary
    // review link once the intake reaches ready_for_review.
    text: {
      title: "Type your symptoms",
      breadcrumb: "Text intake",
      reassure:
        "Describe what's bothering you in your own words - Hindi or English.",
      placeholder: "e.g. Fever since 2 days, dry cough, body ache...",
      langHint: "Hindi and English both accepted",
      emptyTitle: "Add your symptoms to continue",
      emptyBody: "Please type what's bothering you before submitting.",
      voiceAttach: "Add a voice note",
      voiceAttachHint: "Optional - record a voice note to go with your text",
      voiceRecording: "Recording… tap to stop",
      voiceStop: "Stop",
      voicePreview: "Voice note attached",
      voiceRemove: "Remove",
      submit: "Submit",
      submitting: "Structuring…",
      doneBody: "Taken. We're preparing your pre-summary.",
      next: "See your pre-summary",
      voiceTooShortTitle: "Your voice note is too short",
      voiceTooShortBody:
        "Keep the note above 3 seconds, remove it, or type your symptoms instead.",
      uploadErrorTitle: "We couldn't send your recording",
      uploadErrorBody:
        "Your recording is safe. Check your connection and try again.",
      micUnavailableTitle: "We couldn't reach your microphone",
      micUnavailableBody:
        "Check that microphone access is allowed, then try again.",
    },

    // pre-summary review surface (PHASE-7 T18, #362): the AI draft shown to
    // the patient with the honesty cue "AI draft - doctor will verify"
    // (never "AI diagnosis", ADR-0001), the structuring confidence value +
    // light indicator, and - for low_confidence drafts - a calm amber
    // doctor-must-check notice with the forced-review framing (warn, never
    // red). Structured fields render read-only; the patient can edit them
    // and the edits persist via the save-edits route and render as
    // corrections. A continuation CTA points toward consultation booking
    // (FEAT-007, blueprint §5.4/§6.4; PROTO-PHASE-7/8 page is the copy spec).
    preSummary: {
      breadcrumb: "Pre-summary",
      title: "Your pre-summary",
      description:
        "A quick look at what we understood. You can correct anything.",
      bannerLine1: "AI draft - your doctor will verify this",
      bannerLine2:
        "This is not a diagnosis. Your doctor will review and confirm.",
      lowBannerLine1: "AI is not fully sure here",
      lowBannerLine2: "Doctor will need to check this before it can be used.",
      lowVerifyLine:
        "This pre-summary will force a doctor review before any prescription.",
      confidence: "Structuring confidence",
      lowTag: "Low confidence",
      groupTitle: "What the AI understood",
      editBtn: "Edit this summary",
      confirmBtn: "Confirm & continue",
      confirmBtnLow: "Continue to consultation",
      editNote: "Your edits help the doctor understand you better.",
      cancelEdit: "Cancel",
      saveEdit: "Save edits",
      savingEdit: "Saving…",
      correctionsTag: "Corrected",
      doneClean: "Use as is",
      doneLow: "Summary noted. Doctor will verify.",
      bookTitle: "Book consultation with this summary",
      bookSub: "Find a doctor who can review your pre-summary.",
      bookSubLow:
        "Your doctor will verify this pre-summary before it can be used for a prescription.",
      loading: "Checking your pre-summary…",
      emptyTitle: "Your pre-summary isn't ready yet",
      emptyBody:
        "Check again in a moment - the doctor will review your symptoms.",
      loadFailedTitle: "We couldn't load your pre-summary",
      loadFailedBody: "Check your connection and try again.",
      processingTitle: "Your summary is still being prepared",
      processingBody:
        "The AI is finishing your summary. This usually takes a few seconds.",
      processingFailedTitle: "Your summary took too long",
      processingFailedBody:
        "We couldn't find your pre-summary. Please go back and try again.",
      degradedTitle: "Your doctor will review this directly",
      degradedEvidenceTitle: "What the doctor will review",
      degradedVoiceNote: "Your recording has been shared with the doctor.",
      degradedBody:
        "There is no AI pre-summary for this visit. Your doctor will review your symptoms directly.",
      degradedRefresh:
        "This page updates automatically when your doctor takes action.",
      degradedStatusLink: "Back to intake status",
      saveFailedTitle: "We couldn't save your edits",
      saveFailedBody: "Check your connection and try again.",
      fields: {
        chief_complaints: "Chief complaints",
        symptoms: "Symptoms",
        duration: "Duration",
      },
    },

    // status.- intake status list surface (PHASE-7 T19, #363): the patient
    // sees where each submission stands with four statuses - Captured /
    // Structuring / Ready for Review / Recapture needed - mapped 1:1 onto the
    // backend machine status values (T02 state_machine.py). Statuses refresh
    // from the backend (get_intake / get_pre_summary) in-page. A ready
    // pre-summary offers a continue affordance into consultation booking
    // (Phase 8 boundary). Bilingual EN/HI.
    status: {
      breadcrumb: "Status",
      title: "Your intake status",
      description: "Track where your submission stands",
      refresh: "Refresh",
      refreshing: "Checking\u2026",
      captured: "Captured",
      capturedDesc: "Your symptoms have been recorded.",
      structuring: "Structuring",
      structuringDesc: "AI is organizing your information for the doctor.",
      readyForReview: "Ready for Review",
      readyForReviewDesc: "Your information is ready for the doctor to review.",
      rawReviewNote:
        "There is no AI pre-summary for this visit. Your doctor will review the submitted evidence directly.",
      reRecord: "Recapture needed",
      reRecordDesc:
        "We couldn't process your recording clearly. Please re-record or type your symptoms.",
      failed: "Something went wrong",
      failedDesc: "We couldn't process your intake. Please start a new visit.",
      continue: "Continue to consultation",
      reRecordAction: "Re-record",
      typeInstead: "Type instead",
      loading: "Loading your intake status\u2026",
      loadFailedTitle: "We couldn't load your status",
      loadFailedBody: "Check your connection and try again.",
    },
  },

  // doctorConsole.* surface - PHASE-8.1 T12 (#450): the doctor console
  // landing page. Three surfaces: the entry cards into the live Patients and
  // Profile pages, the compact consultation-fee summary (the editor itself
  // lives on Profile since #543), and the review queue (low-confidence first,
  // oldest-first within each group) plus open care cases, with a retry path on
  // load failure. #544 replaced the coming-soon patients/profile placeholders
  // with real entry cards. All copy bilingual en/hi (REQ-006).
  doctorConsole: {
    title: "Doctor console",
    consoleDescription: "Your review queue, open cases and profile",
    entryHeading: "Go to",
    patientsEntryBody: "Everyone who has shared a record with you",
    profileEntryBody: "Practice details, photo and consultation fee",
    feeHeading: "Consultation fee",
    feeUnset: "Not set",
    feeUnsetHelp: "Set a fee so patients can book you.",
    feeEditAction: "Edit in Profile",
    feeLoadFailed: "Could not load your consultation fee.",
    queueHeading: "Review queue",
    queueEmpty: "No pre-summaries waiting for review",
    queueEmptyBody: "A pre-summary lands here once a patient submits a visit.",
    patientFallback: "Patient",
    patientAge: (age: number) => `${age} yrs`,
    sectionsCount: (n: number) => `${n} ${n === 1 ? "section" : "sections"}`,
    queueItemMeta: (id: number) => `Intake #${id}`,
    caseItemMeta: (id: number) => `Case #${id}`,
    verifyChip: "Verify",
    confidenceLabel: "Confidence",
    waitingFor: (time: string) => `Waiting ${time}`,
    reviewAction: "Review",
    casesHeading: "Open cases",
    casesEmpty: "No open care cases",
    casesEmptyBody: "A case opens as soon as you start a consultation.",
    casesIndexTitle: "My cases",
    casesIndexDescription: "Your open care cases",
    stagePreSummary: "Pre-summary",
    stagePrescriptionPending: "Prescription pending",
    stageClosed: "Closed",
    openCaseAction: "Open",
    loadFailed: "Could not load the console.",
    retry: "Try again",
  },

  // doctorProfile.* surface - PHASE-8.1 (#543): the doctor console Profile
  // page, the live destination behind the un-sooned Profile nav entry. Renders
  // and edits the private projection from #542 - photo upload/preview/remove,
  // practice details, experience, languages, about, availability, credential
  // status, notification toggles - and hosts the consultation-fee editor that
  // moved here off the landing (its save still runs the unchanged PATCH route).
  // The public directory entry stays a read-only preview link. All copy
  // bilingual en/hi (REQ-006).
  doctorProfile: {
    title: "My profile",
    description: "Your practice details, photo and consultation fee",
    loadFailed: "Could not load your profile.",
    photoHeading: "Profile photo",
    photoHelp: "JPG, PNG or WebP. Your photo stays private to this page.",
    photoUpload: "Upload photo",
    photoReplace: "Replace photo",
    photoRemove: "Remove photo",
    photoFailed: "Could not update your photo.",
    // #615: the identity band. `photoHeading` no longer titles a card of its own
    // - the picker moved into the band - so it names the control group instead.

    // #615: names the identity band's chip row, which now holds two different
    // things - the verification verdict and the specialty selection. Neither
    // existing label fits: "Specialties" alone would hide the verdict from
    // assistive tech, and the verdict's own label would hide the selection.
    //
    // No `clinicNameLabel` here on purpose. The identity band shows the clinic
    // directly beneath the doctor's name and it is no longer a labelled row, so a
    // separate label would have no label to sit on. `practice_name` is the
    // doctor's own name on this projection, which is why this field says so.
    identityChipsLabel: "Profile status and specialties",
    // The identity band's empty chip. Named "yet" rather than as a dead end: the
    // selection belongs to #608's closed pick-list, and this page has no editor
    // for it yet, so the chip states the absence instead of implying the doctor
    // has no specialty.
    noSpecialtiesYet: "No specialty added yet",
    verified: "Verified",
    notVerified: "Not verified",
    // #615: the two trust bands. The verified band is what the platform derived
    // and checked; the declared band is what the doctor typed, and it SAYS SO in
    // words rather than leaving the distinction to colour alone (blueprint §1.6,
    // §9.4 - a tick the platform cannot substantiate is the failure this avoids).
    // State-NEUTRAL on purpose. This titles the band of things CareSetu checked;
    // it does not assert the outcome, because a doctor whose flag is false would
    // read "Verified by CareSetu" as a claim the backend is not making. The
    // outcome is the activation row's job, one line below, and it reads the same
    // flag the tick reads - so the heading cannot overclaim a verdict its child
    // is about to contradict.
    verifiedBandTitle: "Checked by CareSetu",
    verifiedBandHelp:
      "CareSetu checks your credentials and your activation status.",
    // #623: relabelled from "Activation state". The row shows `verified`,
    // which is a COMPOSITE - activation state AND every credential's dates - so
    // the old label made an Active doctor with one lapsed credential read
    // "Activation state: Not verified", which is a false claim about their
    // activation. The label now names the quantity that is actually rendered.
    // Label and value still come from one flag, so the band cannot claim one
    // verdict and show another.
    verificationStateLabel: "Verification status",
    // The tick's own accessible name. The tick is decorative next to a text
    // verdict in the same row, so the name says what it means rather than being
    // read as "check mark" and leaving the doctor to work out what was checked.
    verifiedTickLabel: "CareSetu verified this profile",
    declaredBandTitle: "Your details",
    declaredBandHelp:
      "These are the details you typed. CareSetu has not checked them.",
    // The sticky anchor-chip index: an accessible name for the landmark, plus the
    // section titles it jumps between and those sections' own headings reuse.
    sectionIndexLabel: "Sections",
    practiceSectionTitle: "Practice",
    addressSectionTitle: "Address",
    aboutSectionTitle: "About",
    credentialsHeading: "Credentials",
    credentialsEmpty: "No credentials on file",
    credentialExpires: (date: string) => `Valid until ${date}`,
    credentialStatus: {
      pending: "Pending review",
      verified: "Verified",
      expired: "Expired",
      revoked: "Revoked",
      reverification_failed: "Re-verification failed",
    },
    // The two credential kinds a doctor partner may hold; any other literal the
    // API sends falls back to its own text rather than going unlabelled.
    credentialType: {
      medical_registration: "Medical registration",
      qualification_certificate: "Qualification certificate",
    },
    experienceLabel: "Years of experience",
    // #617: the languages are a closed selection of chips now, not a comma-
    // separated box, so `languagesHelp` says "choose" rather than "separate with
    // commas" - the old sentence described an editor this surface no longer has.
    // `languagesPlaceholder` is gone with that editor.
    experienceHelp: "Whole years, up to 60",
    languagesLabel: "Languages you consult in",
    languagesHelp: "Choose every language you see patients in",
    aboutLabel: "About",
    aboutHelp: "In your own words. Patients read this before they choose you.",
    aboutPlaceholder: "Tell patients about your practice",
    // #617: the consulting days and the consulting hours, which #610 split out of
    // the retired free-text `availability` blob. The days are a closed selection
    // of the week; the hours stay PROSE, and the copy says why - the platform
    // does not book appointments, so an editor that invited a weekly template
    // would be promising something the server cannot keep.
    consultingDaysLabel: "Days you consult on",
    consultingDaysHelp: "Choose every day you see patients",
    consultingHoursLabel: "Consulting hours",
    consultingHoursHelp:
      "In your own words. CareSetu does not book appointments.",
    consultingHoursPlaceholder: "e.g. Mon-Sat mornings, Saturday after 5 pm",
    // #617: the Practice card's copy, and the only place the doctor's name is
    // named now. The retired `PracticeFields` labelled this row `practiceNameLabel`,
    // "Full name / practice name", which hedged between two readings the card cannot
    // hedge between: this field IS the full name, and the clinic name is the row
    // below it.
    practiceSectionHelp:
      "The name and the kinds of care patients see when they choose you.",
    practiceFullNameLabel: "Full name",
    practiceFullNameHelp: "The name patients see",
    practiceClinicNameLabel: "Clinic name",
    practiceClinicNameHelp: "The building you see patients in. Optional.",
    practiceSpecialtiesLabel: "Specialties",
    practiceSpecialtiesHelp:
      "Choose every kind of care you offer. You may choose more than one.",
    // #617: the three closed vocabularies' labels, keyed by the DOMAIN's machine
    // value rather than by a slug of this surface's own. The key is what the wire
    // carries and what the column is keyed on, so a label can be reworded in
    // either locale without touching a value or a chip test hook.
    //
    // In English every label equals its own value, and that is deliberate rather
    // than a lazy copy: these are English medical terms already, so an "English
    // label" for them can only differ by rewriting a term doctors use. The map is
    // still spelled out, because a dictionary whose English half is derived is a
    // dictionary whose Hindi half nobody can diff against it.
    specialtyLabels: {
      "General Physician": "General Physician",
      Pediatrician: "Pediatrician",
      Gynecologist: "Gynecologist",
      Dentist: "Dentist",
      "General Surgeon": "General Surgeon",
      "Orthopedic Surgeon": "Orthopedic Surgeon",
      Ophthalmologist: "Ophthalmologist",
      "ENT Specialist": "ENT Specialist",
      Dermatologist: "Dermatologist",
      Psychiatrist: "Psychiatrist",
      Cardiologist: "Cardiologist",
      Neurologist: "Neurologist",
      Gastroenterologist: "Gastroenterologist",
      Urologist: "Urologist",
      Nephrologist: "Nephrologist",
      Pulmonologist: "Pulmonologist",
      Endocrinologist: "Endocrinologist",
      Oncologist: "Oncologist",
      "Ayurvedic Practitioner": "Ayurvedic Practitioner",
      "Homeopathy Practitioner": "Homeopathy Practitioner",
    },
    languageLabels: {
      Assamese: "Assamese",
      Bengali: "Bengali",
      Bodo: "Bodo",
      Dogri: "Dogri",
      English: "English",
      Gujarati: "Gujarati",
      Hindi: "Hindi",
      Kannada: "Kannada",
      Kashmiri: "Kashmiri",
      Konkani: "Konkani",
      Maithili: "Maithili",
      Malayalam: "Malayalam",
      Manipuri: "Manipuri",
      Marathi: "Marathi",
      Nepali: "Nepali",
      Odia: "Odia",
      Punjabi: "Punjabi",
      Sanskrit: "Sanskrit",
      Santali: "Santali",
      Sindhi: "Sindhi",
      Tamil: "Tamil",
      Telugu: "Telugu",
      Urdu: "Urdu",
    },
    dayLabels: {
      Monday: "Monday",
      Tuesday: "Tuesday",
      Wednesday: "Wednesday",
      Thursday: "Thursday",
      Friday: "Friday",
      Saturday: "Saturday",
      Sunday: "Sunday",
    },
    // The one client-side rule the Practice card can state in a sentence.
    practiceNameRequired: "Enter your name.",
    practiceNameTooLong: "This name is too long.",
    practiceClinicNameTooLong: "This clinic name is too long.",
    practiceExperienceInvalid: "Enter whole years between 0 and 60.",
    // The expected-4xx copy for a 422 whose `details.errors[].path` names the
    // selection field. Client sentence, never the API's own `reason`
    // (api-standards §2, blueprint §9.5) - the API says which member it refused,
    // and a doctor who tapped a chip cannot have meant the value it rejected.
    practiceSpecialtiesRejected:
      "CareSetu could not accept one of the specialties you chose. Choose again and save.",
    practiceSaved: "Practice details saved.",
    practiceSaveFailed: "Could not save your practice details.",
    aboutSectionHelp:
      "Your own words, the languages you consult in, and the days you see patients.",
    aboutTooLong: "This text is too long.",
    aboutSaved: "About section saved.",
    aboutSaveFailed: "Could not save your about section.",
    languagesRejected:
      "CareSetu could not accept one of the languages you chose. Choose again and save.",
    consultingDaysRejected:
      "CareSetu could not accept one of the days you chose. Choose again and save.",
    // #617: the Notification card's copy. `notificationsHeading` above titles the
    // section and its anchor chip; these are the card's own strings.
    notificationsHelp: "Choose what CareSetu tells you about.",
    notificationGroupLabel: "Notification choices",
    notificationPreferencesRejected:
      "CareSetu could not accept one of these choices. Try again.",
    notificationsSaved: "Notification choices saved.",
    notificationsSaveFailed: "Could not save your notification choices.",
    // #616: the Address section card's copy, which replaces the free-text
    // `addressLabel` this card took over - the field that key named is gone with
    // the declared band's whole-form textarea, because the address now has
    // exactly one editor on the page and this card is it.
    //
    // The two derived rows (district, state) are labelled and read-only, and they
    // render empty today: the profile projection and the address write's answer
    // both stop at the PIN code, and the centroid table's own district/region
    // columns are not carried through the position decision (#603), so there is
    // nothing for the client to read them from. The labels stay so the shape is
    // on the page and the gap is a visible empty value, not a missing row.
    addressSectionHelp:
      "CareSetu works out your map position from your PIN code, so there are no coordinates to enter.",
    addressLineLabel: "Building and street",
    addressLineHelp: "Building, street and locality",
    addressLandmarkLabel: "Landmark (optional)",
    addressLocalityLabel: "Locality",
    addressCityLabel: "City",
    addressPinLabel: "PIN code",
    addressPinHelp: "Six digits",
    addressDistrictLabel: "District",
    addressStateLabel: "State",
    addressDerivedHelp:
      "CareSetu fills these in from your PIN code. They are not editable.",
    addressDerivedEmpty: "Not available",
    // The client-side mirror of the server's own PIN rule (#603: an Indian PIN code
    // is exactly six ASCII digits), refused on submit rather than by rewriting
    // what the doctor typed.
    addressPinInvalid: "Enter the six-digit PIN code.",
    // The expected-4xx copy for a 422 whose `details.errors[].path` names the PIN
    // field, keyed on the envelope's stable code and never on its `reason`: one
    // client sentence covers both machine reasons because a doctor cannot tell a
    // length failure from an unlisted code, and the API's prose is not copy this
    // surface may show (api-standards §2, ui-blueprint §9.5).
    addressPinUnresolved:
      "CareSetu cannot place this PIN code. Check the six digits and save again.",
    // The belt notice, and it is a warning rather than a refusal: the save
    // succeeded and only this doctor's own listing surfaces as an
    // outside-your-area result, which is why the copy says so instead of calling
    // the address invalid (ADR-0021, the wider-area fallback).
    addressOutsideBelt: (km: string) =>
      `This address is ${km} km from the centre of the area CareSetu serves. Your address is saved, and patients searching nearby will see you as a result from outside your area.`,
    // The form summary (blueprint §9.5): a failed submit states how many
    // fields need attention and takes focus to the first of them. A server path
    // the card cannot map lands here too, as client copy - a raw path or the
    // API's own reason is never shown to a doctor.
    //
    // #617: `addressInvalidSummary`/`addressUnmappedField` were address-prefixed
    // names for the two sentences every saving card needs. They are section-
    // generic, and #617 needs them on three more cards, so one key each replaces
    // the pair rather than four copies of the same sentence in four locales.
    invalidSummary: (count: number) =>
      count === 1
        ? "Check the highlighted field and save again."
        : `Check the ${count} highlighted fields and save again.`,
    unmappedField:
      "CareSetu could not check one of these fields. Review this section and save again.",
    addressSaved: "Address saved.",
    addressSaveFailed: "Could not save your address.",
    notificationsHeading: "Notifications",
    notificationLabels: {
      new_consultations: "New consultations",
      record_shared: "Records shared with you",
      pre_summary_ready: "Pre-summaries ready to review",
      case_updates: "Case updates",
      credential_status: "Credential status changes",
    },
    save: "Save changes",
    // #617 retired the page's one whole-form save, and with it the one string that
    // said "Profile saved." / "Could not save your profile." for every section at
    // once. Each saving card now owns its own saved and failed sentence, next to the
    // section those sentences are about.
    //
    // #605: the reusable section shell's dirty hint - the only copy the shell
    // presents that no section owns, so it ships here in both locales like the
    // rest of the surface.
    unsavedChanges: "Unsaved changes",
    publicPreviewHeading: "Public profile",
    publicPreviewHelp:
      "This is how patients see you in the directory. It is read-only here.",
    publicPreviewAction: "View public profile",
    // #618: the LIVE preview - the public profile rendered from the fields being
    // edited, updating as they are typed. It says where it comes from and that the
    // tick in it is CareSetu's, because a doctor who cannot tell those apart is
    // being shown a verification they did not earn. `Show`/`Hide` are the mobile
    // disclosure's own two states (blueprint §9.3 progressive disclosure).
    livePreviewHeading: "Live preview",
    livePreviewHelp:
      "Updates as you type. The tick is CareSetu's, not something you set.",
    livePreviewShow: "Show",
    livePreviewHide: "Hide",
      credentialsHeading: "प्रमाण",
      credentialsEmpty: "कोई प्रमाण दर्ज नहीं",
      credentialExpires: (date: string) => `${date} तक वैध`,
      credentialStatus: {
        pending: "समीक्षा बाकी",
        verified: "सत्यापित",
        expired: "मान्यता समाप्त",
        revoked: "निरस्त",
        reverification_failed: "पुनः सत्यापन विफल",
      },
      credentialType: {
        medical_registration: "चिकित्सा पंजीकरण",
        qualification_certificate: "योग्यता प्रमाणपत्र",
      },
      experienceLabel: "अनुभव के वर्ष",
      // #617: भाषाएँ अब अलग-अलग चिप्स का बंद चयन हैं, कॉमा से अलग करने वाला
      // बॉक्स नहीं - इसलिए `languagesHelp` अब "चुनें" कहता है, "कॉमा से अलग
      // करके लिखें" नहीं, क्योंकि वह वाक्य उस एडिटर का वर्णन था जो इस सतह पर
      // अब नहीं है। वह एडिटर उसके साथ ही `languagesPlaceholder` भी चला गया।
      experienceHelp: "पूरे वर्ष, अधिकतम 60",
      languagesLabel: "आप जिन भाषाओं में परामर्श करते हैं",
      languagesHelp: "हर वह भाषा चुनें जिसमें आप मरीज़ों को देखते हैं",
      aboutLabel: "आपके बारे में",
      aboutHelp: "अपने शब्दों में। मरीज़ आपको चुनने से पहले यह पढ़ते हैं।",
      aboutPlaceholder: "मरीज़ों को अपनी प्रैक्टिस के बारे में बताएँ",
      // #617: परामर्श के दिन और परामर्श का समय, जिन्हें #610 ने सेवा हटाए गए
      // मुक्त-पाठ `availability` ब्लॉब से अलग किया। दिन हफ़्ते का बंद चयन हैं;
      // समय मुक्त-पाठ रहता है, और कॉपी बताती है क्यों - प्लेटफ़ॉर्म अपॉइंटमेंट
      // बुक नहीं करता, इसलिए साप्ताहिक टेम्पलेट खातूला एडिटर ऐसा वादा करता जो
      // सर्वर नहीं निभा सकता।
      consultingDaysLabel: "जिन दिनों आप परामर्श करते हैं",
      consultingDaysHelp: "हर वह दिन चुनें जिस दिन आप मरीज़ों को देखते हैं",
      consultingHoursLabel: "परामर्श का समय",
      consultingHoursHelp:
        "अपने शब्दों में। CareSetu अपॉइंटमेंट बुक नहीं करता।",
      consultingHoursPlaceholder: "जैसे सोम-शनि सुबह, शनि शाम 5 बजे के बाद",
      // #617: प्रैक्टिस कार्ड की कॉपी, और अब डॉक्टर के नाम का उल्लेख सिर्फ़ यहीं है।
      // हटाया गया `PracticeFields` इस पंक्ति को `practiceNameLabel` ("पूरा नाम /
      // प्रैक्टिस का नाम") से सजाता था, जो दो पढ़ों के बीच हिजकत करता था और यह कार्ड
      // नहीं कर सकता: यह फ़ील्ड पूरा नाम ही है, और क्लिनिक का नाम इसके ठीक नीचे है।
      practiceSectionHelp:
        "वह नाम और वे देखभाल के प्रकार जो मरीज़ आपको चुनते समय देखते हैं।",
      practiceFullNameLabel: "पूरा नाम",
      practiceFullNameHelp: "वह नाम जो मरीज़ देखते हैं",
      practiceClinicNameLabel: "क्लिनिक का नाम",
      practiceClinicNameHelp:
        "वह इमारत जिसमें आप मरीज़ों को देखते हैं। वैकल्पिक।",
      practiceSpecialtiesLabel: "विशेषज्ञताएँ",
      practiceSpecialtiesHelp:
        "देखभाल का हर प्रकार चुनें जो आप देते हैं। आप एक से अधिक चुन सकते हैं।",
      // #617: तीनों बंद शब्दकोशों के लेबल, सतह के अपने स्लग की बजाय डोमेन के
      // मशीन मान से कुंजीबद्ध। कुंजी वही है जो वायर ले जाता है और जिस पर कॉलम
      // बना है, इसलिए किसी भी लोकेल में लेबल बदलने के लिए न मान बदलना पड़े, न
      // चिप का टेस्ट हुक।
      specialtyLabels: {
        "General Physician": "सामान्य चिकित्सक",
        Pediatrician: "बाल रोग विशेषज्ञ",
        Gynecologist: "स्त्री रोग विशेषज्ञ",
        Dentist: "दंत चिकित्सक",
        "General Surgeon": "सामान्य शल्य चिकित्सक",
        "Orthopedic Surgeon": "हड्डी-जोड़ शल्य चिकित्सक",
        Ophthalmologist: "नेत्र चिकित्सक",
        "ENT Specialist": "कान-नाक-गला विशेषज्ञ",
        Dermatologist: "त्वचा विशेषज्ञ",
        Psychiatrist: "मनोचिकित्सक",
        Cardiologist: "हृदय विशेषज्ञ",
        Neurologist: "तंत्रिका विशेषज्ञ",
        Gastroenterologist: "पाचन-विशेषज्ञ",
        Urologist: "मूत्ररोग विशेषज्ञ",
        Nephrologist: "गुर्दा-विशेषज्ञ",
        Pulmonologist: "फेफड़ा-विशेषज्ञ",
        Endocrinologist: "अंतःस्रावी-विशेषज्ञ",
        Oncologist: "कैंसर-विशेषज्ञ",
        "Ayurvedic Practitioner": "आयुर्वेदिक चिकित्सक",
        "Homeopathy Practitioner": "होम्योपैथी चिकित्सक",
      },
      languageLabels: {
        Assamese: "असमिया",
        Bengali: "बंगाली",
        Bodo: "बोडो",
        Dogri: "डोगरी",
        English: "अंग्रेज़ी",
        Gujarati: "गुजराती",
        Hindi: "हिंदी",
        Kannada: "कन्नड़",
        Kashmiri: "कश्मीरी",
        Konkani: "कोंकणी",
        Maithili: "मैथिली",
        Malayalam: "मलयालम",
        Manipuri: "मणिपुरी",
        Marathi: "मराठी",
        Nepali: "नेपाली",
        Odia: "ओडिया",
        Punjabi: "पंजाबी",
        Sanskrit: "संस्कृत",
        Santali: "संताली",
        Sindhi: "सिंधी",
        Tamil: "तमिल",
        Telugu: "तेलुगु",
        Urdu: "उर्दू",
      },
      dayLabels: {
        Monday: "सोमवार",
        Tuesday: "मंगलवार",
        Wednesday: "बुधवार",
        Thursday: "गुरुवार",
        Friday: "शुक्रवार",
        Saturday: "शनिवार",
        Sunday: "रविवार",
      },
      practiceNameRequired: "अपना नाम दर्ज करें।",
      practiceNameTooLong: "यह नाम बहुत लंबा है।",
      practiceClinicNameTooLong: "यह क्लिनिक का नाम बहुत लंबा है।",
      practiceExperienceInvalid: "0 से 60 के बीच पूरे वर्ष दर्ज करें।",
      practiceSpecialtiesRejected:
        "CareSetu आपकी चुनी हुई विशेषज्ञताओं में से किसी को स्वीकार नहीं कर सका। दोबारा चुनें और सहेजें।",
      practiceSaved: "प्रैक्टिस की जानकारी सहेज ली गई।",
      practiceSaveFailed: "प्रैक्टिस की जानकारी सहेजी नहीं जा सकी।",
      aboutSectionHelp:
        "आपके अपने शब्द, वे भाषाएँ जिनमें आप परामर्श करते हैं, और वे दिन जिनमें आप मरीज़ों को देखते हैं।",
      aboutTooLong: "यह पाठ बहुत लंबा है।",
      aboutSaved: "परिचय अनुभाग सहेज लिया गया।",
      aboutSaveFailed: "परिचय अनुभाग सहेजा नहीं जा सका।",
      languagesRejected:
        "CareSetu आपकी चुनी हुई भाषाओं में से किसी को स्वीकार नहीं कर सका। दोबारा चुनें और सहेजें।",
      consultingDaysRejected:
        "CareSetu आपके चुने दिनों में से किसी को स्वीकार नहीं कर सका। दोबारा चुनें और सहेजें।",
      // #617: सूचना कार्ड की कॉपी। ऊपर `notificationsHeading` अनुभाग और उसके
      // एंकर चिप का शीर्षक है; ये कार्ड के अपने तार हैं।
      notificationsHelp: "चुनें कि CareSetu आपको किस बात की सूचना दे।",
      notificationGroupLabel: "सूचना संबंधी चयन",
      notificationPreferencesRejected:
        "CareSetu इन चयनों में से किसी को स्वीकार नहीं कर सका। फिर से कोशिश करें।",
      notificationsSaved: "सूचना संबंधी चयन सहेज लिए गए।",
      notificationsSaveFailed: "सूचना संबंधी चयन सहेजे नहीं जा सके।",
      // #616: पता कार्ड की कॉपी, जो मुक्त-पाठ वाले `addressLabel` की जगह आई -
      // वह फ़ील्ड उसके साथ ही चला गया, क्योंकि अब पेज पर पते का एक ही एडिटर है
      // और वह यही कार्ड है।
      //
      // दो निगमित पंक्तियाँ (ज़िला, राज्य) लेबल सहित पढ़ने-योग्य हैं और आज ख़ाली
      // दिखती हैं: प्रोफ़ाइल प्रोजेक्शन और पते की राइट का जवाब दोनों पिन कोड पर
      // रुकते हैं, और सेंट्रॉइड तालिका के अपने ज़िला/क्षेत्र कॉलम स्थिति के निर्णय
      // (#603) से गुजरते नहीं, इसलिए क्लाइंट के पास पढ़ने को कुछ नहीं है। लेबल रहते
      // हैं ताकि आकृति पेज पर रहे और अभाव किसी छूटी पंक्ति के रूप में नहीं, एक
      // दिखने वाले ख़ाली मान के रूप में दिखे।
      addressSectionHelp:
        "आपका मानचित्र स्थान CareSetu आपके पिन कोड से निकालता है, इसलिए नक़्शे के निर्देशांक भरने की ज़रूरत नहीं है।",
      addressLineLabel: "इमारत और सड़क",
      addressLineHelp: "इमारत, सड़क और इलाका",
      addressLandmarkLabel: "पहचान की जगह (वैकल्पिक)",
      addressLocalityLabel: "इलाका",
      addressCityLabel: "शहर",
      addressPinLabel: "पिन कोड",
      addressPinHelp: "छह अंक",
      addressDistrictLabel: "ज़िला",
      addressStateLabel: "राज्य",
      addressDerivedHelp:
        "ये CareSetu आपके पिन कोड से भरता है। इन्हें नहीं बदला जा सकता।",
      addressDerivedEmpty: "उपलब्ध नहीं",
      addressPinInvalid: "छह अंकों का पिन कोड दर्ज करें।",
      addressPinUnresolved:
        "CareSetu इस पिन कोड की जगह नहीं बता सकता। छह अंक जाँचें और फिर सहेजें।",
      addressOutsideBelt: (km: string) =>
        `यह पता उस इलाक़े के केंद्र से ${km} किमी दूर है जिसकी सेवा CareSetu करता है। आपका पता सहेज लिया गया है, और आस-पास खोजने वाले मरीज़ आपको आपके इलाक़े के बाहर के परिणाम के रूप में देखेंगे।`,
      invalidSummary: (count: number) =>
        count === 1
          ? "चिह्नित फ़ील्ड जाँचें और फिर सहेजें।"
          : `चिह्नित ${count} फ़ील्ड जाँचें और फिर सहेजें।`,
      unmappedField:
        "CareSetu इनमें से किसी फ़ील्ड की जाँच नहीं कर सका। यह अनुभाग दोबारा देखें और सहेजें।",
      addressSaved: "पता सहेज लिया गया।",
      addressSaveFailed: "आपका पता सहेजा नहीं जा सका।",
      notificationsHeading: "सूचनाएँ",
      notificationLabels: {
        new_consultations: "नई परामर्श",
        record_shared: "आपके साथ साझा किए गए रिकॉर्ड",
        pre_summary_ready: "समीक्षा के लिए तैयार प्री-सारांश",
        case_updates: "केस अपडेट",
        credential_status: "प्रमाण स्थिति में बदलाव",
      },
      save: "बदलाव सहेजें",
      // #617: the whole-form save is gone, so the one sentence every section shared
      // goes with it - see the English branch for why. Each card's own saved and
      // failed sentences sit next to its own section title.
      unsavedChanges: "असहेजे बदलाव",
      publicPreviewHeading: "सार्वजनिक प्रोफ़ाइल",
      publicPreviewHelp:
        "मरीज़ आपको डायरेक्टरी में इसी तरह देखते हैं। यहाँ यह केवल-पढ़ने के लिए है।",
      publicPreviewAction: "सार्वजनिक प्रोफ़ाइल देखें",
 origin/main
      feeHeading: "परामर्श शुल्क",
      feeHelp:
        "वह शुल्क सेट करें जो मरीज़ आपको चुनने पर देखें। सेट न होने तक खाली रहेगा।",
      feeFieldLabel: "शुल्क (\u20B9)",
      feeFieldPlaceholder: "जैसे 400",
      saveFee: "शुल्क सहेजें",
      clearFee: "शुल्क हटाएँ",
      feeInvalid: "0 या उससे अधिक शुल्क दर्ज करें।",
      feeSaved: "शुल्क सहेजा गया।",
      feeSaveFailed: "शुल्क सहेजा नहीं जा सका।",
    },

    // doctorPatients.* सतह - PHASE-8.1 (#541): डॉक्टर कंसोल का मरीज़ पेज
    // (US-11..US-19)। व्युत्पन्न सूची API से वर्तमान/पूर्व समूह, नाम खोज,
    // अनुमत-क्षेत्र बैज और नवीनतम केस अवस्था; प्रति-मरीज़ विवरण दृश्य में
    // संपर्क/फोटो/परामर्श-इतिहास/स्वास्थ्य-पृष्ठभूमि अनुभाग, जहाँ बिना अनुमति
    // वाला अनुभाग शांत "साझा नहीं" अवस्था दिखाता है - कभी त्रुटि नहीं। अवस्था
    // चिप doctorConsole.stage* और प्रविष्टि-प्रकार लेबल record.badge* से लिए
    // गए हैं। सभी कॉपी द्विभाषी en/hi (REQ-006)।
    doctorPatients: {
      title: "मेरे मरीज़",
      description: "वर्तमान में रिकॉर्ड साझा करने वाले और पूर्व के मरीज़",
      searchPlaceholder: "नाम से खोजें",
      currentHeading: "वर्तमान",
      pastHeading: "पूर्व",
      patientsEmpty: "अभी कोई मरीज़ नहीं",
      currentEmpty: "कोई वर्तमान मरीज़ नहीं",
      pastEmpty: "कोई पूर्व मरीज़ नहीं",
      noResultsTitle: "कोई मरीज़ नहीं मिला",
      noResultsBody: "आपकी खोज से मेल खाता कोई मरीज़ नाम नहीं है।",
      noCaseStage: "कोई खुला मामला नहीं",
      openPatientAction: "खोलें",
      loadFailed: "आपके मरीज़ लोड नहीं हो सके।",
      retry: "फिर से कोशिश करें",
      backToPatients: "मरीज़ों पर वापस",
      loadFailedDetail: "यह मरीज़ लोड नहीं हो सका।",
      notSharedTitle: "साझा नहीं",
      notSharedBody: "मरीज़ ने यह अनुभाग आपसे साझा नहीं किया है।",
      contactHeading: "संपर्क",
      ageLabel: "आयु",
      genderLabel: "लिंग",
      areaLabel: "क्षेत्र",
      emergencyContactLabel: "आपातकालीन संपर्क",
      notRecorded: "दर्ज नहीं",
      consultationHistoryHeading: "परामर्श इतिहास",
      consultationHistoryEmpty: "अभी कोई परामर्श नहीं।",
      healthBackgroundHeading: "स्वास्थ्य पृष्ठभूमि",
      healthBackgroundEmpty: "अभी कोई स्वास्थ्य पृष्ठभूमि साझा नहीं।",
      caseWorkspaceHeading: "केस वर्कस्पेस",
      openCaseAction: "मामला खोलें",
      noPhoto: "कोई फोटो नहीं",
      photoAlt: (name: string) => `${name} की फोटो`,
      bloodGroupLabel: "रक्त समूह",
      conditionsLabel: "बीमारियाँ",
      allergiesLabel: "एलर्जी",
      medicationsLabel: "दवाइयाँ",
      immunizationsLabel: "टीके",
      familyHistoryLabel: "पारिवारिक इतिहास",
      noneRecorded: "कोई दर्ज नहीं",
      scopeBadge: {
        consultations: "परामर्श",
        prescriptions: "नुस्ख़े",
        lab_results: "प्रयोगशाला परिणाम",
        metrics: "माप",
        health_background: "स्वास्थ्य पृष्ठभूमि",
        full_record: "पूरा रिकॉर्ड",
      },
    },

    // caseWorkspace.* सतह - PHASE-8.1 T13/T14 (#451/#452): केस वर्कस्पेस।
    // दोनों प्रवेश मार्ग (कतार -> review/[intakeId] और खुले मामले -> cases/[caseId]):
    // केस स्टेज चिप, अनिवार्य समीक्षा आवश्यकता, पूरा प्री-सारांश, मरीज़ का सहमति-प्राप्त
    // स्वास्थ्य इतिहास, एक-क्रिया में समीक्षा+अंतिमकरण, और नुस्ख़ा-लंबित की ओर हैंडशेक।
    // नुस्ख़ा मसौदा (US-18/#452): AI मसौदा अनुरोध, संपादन योग्य rx-आइटम पंक्तियाँ,
    // रिवीज़न सहेजना, और चालू वर्किंग रिवीज़न को पुनः लोड करना। अनुमोदन/अस्वीकृति #453 में।
    caseWorkspace: {
      title: "केस वर्कस्पेस",
      backToConsole: "कंसोल पर वापस",
      stageLabel: "अवस्था",
      forcedReviewChip: "समीक्षा ज़रूरी",
      forcedReviewDetail:
        "इस प्री-सारांश का विश्वास कम है और किसी नुस्ख़े से पहले आपकी समीक्षा ज़रूरी है।",
      summaryHeading: "समीक्षा के लिए प्री-सारांश",
      confidenceLabel: "विश्वास",
      chiefComplaintsLabel: "मुख्य शिकायतें",
      symptomsLabel: "लक्षण",
      durationLabel: "अवधि",
      durationNotSet: "दर्ज नहीं",
      patientEditsLabel: "मरीज़ के संपादन",
      patientEditsNone: "कोई मरीज़ संपादन नहीं",
      reviewStateLabel: "समीक्षा स्थिति",
      reviewStateDraft: "आपकी समीक्षा की प्रतीक्षा",
      reviewStateReviewed: "समीक्षित",
      reviewStateFinal: "अंतिम",
      attributionLabel: "श्रेय",
      reviewedOnLabel: "समीक्षा तिथि",
      notReviewedYet: "अभी श्रेय नहीं",
      historyHeading: "मरीज़ का इतिहास",
      historyConsentNote: "केवल वही जो मरीज़ ने साझा करने की सहमति दी।",
      historyEmpty: "अभी कोई इतिहास नहीं।",
      historyLoadFail: "मरीज़ का इतिहास लोड नहीं हो सका।",
      // PHASE-8.1 #484: केस वर्कस्पेस के भीतरी टैब + मूल इंटेक प्रतिलेख + ऑडियो।
      tabPreSummary: "प्री-सारांश",
      tabHistory: "इतिहास",
      tabPrescription: "नुस्ख़ा",
      // केस स्टेपर चरण लेबल (FEAT-008, PROTO-8)
      consultCompleteStep: "परामर्श पूर्ण",
      rxPendingStep: "नुस्ख़ा लंबित",
      issuedStep: "जारी",
      caseProgressLabel: "केस प्रगति",
      transcriptHeading: "मूल इंटेक",
      transcriptEmpty: "इस इंटेक के लिए कोई प्रतिलेख उपलब्ध नहीं है।",
      transcriptLoadFail: "इंटेक प्रतिलेख लोड नहीं हो सका।",
      audioPlayLabel: "रिकॉर्डिंग चलाएँ",
      audioLoadFail: "रिकॉर्डिंग लोड नहीं हो सकी।",
      loadFailed: "यह केस वर्कस्पेस लोड नहीं हो सका।",
      retry: "फिर कोशिश करें",
      // PHASE-8.1 #547: समीक्षा मार्ग का री-स्टाइल सतह - अपना शीर्षक वाला
      // समीक्षा-एक्शन कार्ड, और शांत "केस नहीं दिख रहा" खाली अवस्था। यह
      // प्रतिलेख केवल अवलोकन बताता है (खुली सूची में कोई केयर केस नहीं), कारण
      // का दावा नहीं: कतार से शुरू समीक्षा में आउटबॉक्स कंज़्यूमर के केस बनाने
      // तक केस नहीं होता, और अंतिम करने के बाद की दोबारा पढ़ी भी खाली आ सकती है।
      reviewActionHeading: "आपकी समीक्षा",
      handshakeHeading: "परामर्श",
      casePendingTitle: "केयर केस नहीं दिख रहा",
      casePendingBody:
        "इस प्री-सारांश का कोई केयर केस अभी आपके खुले मामलों में नहीं है। प्री-सारांश अंतिम होने पर केस बनता है।",
      finalizeAction: "अंतिम करें + समीक्षा का श्रेय",
      finalizeHelp:
        "एक क्रिया से आपकी समीक्षा दर्ज होती है और प्री-सारांश अंतिम हो जाता है।",
      finalizeSuccess: "प्री-सारांश अंतिम हुआ और आपको श्रेय मिला।",
      finalizeFail: "यह प्री-सारांश अंतिम नहीं हो सका।",
      handshakeAction: "परामर्श पूर्ण करें",
      handshakeHelp: "मामले को नुस्ख़ा-लंबित अवस्था में ले जाता है।",
      handshakeFail: "परामर्श पूर्ण नहीं हो सका।",
      handshakeSuccess: "परामर्श पूर्ण - मामला अब नुस्ख़ा-लंबित है।",
      prescriptionPendingCta: "नीचे नुस्ख़ा संपादक तैयार है।",
      // PHASE-8.1 #484: नुस्ख़ा टैब की अवस्था-लॉक - किसी नुस्ख़े से पहले परामर्श
      // पूर्ण होना चाहिए। जन्मा मामला हमेशा अंतिम प्री-सारांश रखता है; बाकी
      // कदम परामर्श-पूर्ण हैंडशेक है, और क्रिया प्री-सारांश टैब पर ले जाती है।
      rxLockTitle: "नुस्ख़ा अभी खुला नहीं",
      rxLockSubtitle: "नुस्ख़ा खोलने के लिए ये दोनों पूरे होने चाहिए:",
      rxLockPreSummary: "प्री-सारांश अंतिम",
      rxLockHandshake: "परामर्श पूर्ण दर्ज",
      rxLockGoToSummary: "सारांश पर जाएँ",
      rxLockMarkComplete: "पूर्ण दर्ज करें",
      rxLockDone: "प्री-सारांश अंतिम",
      rxLockPending: "परामर्श पूर्ण दर्ज",
      rxLockAction: "परामर्श पूर्ण करें",
      prescriptionHeading: "नुस्ख़ा",
      prescriptionHelp:
        "AI मसौदा माँगें, फिर सहेजने से पहले आइटमों को अपने नैदानिक निर्णय के अनुसार संपादित करें।",
      requestDraftAction: "AI मसौदा माँगें",
      requestingDraft: "माँग रहा है",
      requestDraftFail: "AI मसौदा बनाया नहीं जा सका।",
      draftCapReached:
        "इस मामले के लिए AI मसौदा सीमा पूरी हो गई है। मौजूदा मसौदा संपादित करके सहेजें।",
      noDraftYet:
        "अभी कोई नुस्ख़ा मसौदा नहीं है। शुरू करने के लिए नीचे अपना इनपुट जोड़ें।",
      // PHASE-8.1 T6 (#490): खाली अवस्था में डॉक्टर-इनपुट कैप्चर सतह -
      // वॉइस नोट / फोटो / टाइप किया हुआ जोड़ डॉक्टर मीडिया मार्ग से होकर
      // doctor-input पर media_ref भेजते हैं; AI मसौदा गेट और मैनुअल लेखन भी
      // यहीं हैं। अस्वीकृति कोड विशेष संदेशों पर मैप होते हैं (#487)।
      doctorInputHelp:
        "यह नुस्ख़ा बनाने में मदद के लिए वॉइस नोट, फोटो या छोटा टाइप किया हुआ जोड़ साझा करें।",
      voiceNoteAction: "वॉइस नोट",
      photoAction: "फोटो",
      addendumLabel: "टाइप किया हुआ जोड़ (वैकल्पिक)",
      addendumPlaceholder: "जैसे - खुराक नोट या निर्देश",
      addendumSubmit: "जोड़ संलग्न करें",
      inputSubmitting: "अपलोड हो रहा है",
      doctorInputFail: "आपका इनपुट संलग्न नहीं हो सका। फिर कोशिश करें।",
      doctorInputReceived: "इनपुट संलग्न - अब आप AI मसौदा माँग सकते हैं।",
      requestDraftBlocked:
        "AI मसौदा सक्षम करने के लिए वॉइस नोट, फोटो या टाइप किया हुआ जोड़ संलग्न करें।",
      manualAuthoringAction: "खुद नुस्ख़ा लिखें",
      manualAuthoringHelp:
        "नुस्ख़ा आइटम खुद लिखें - AI की ज़रूरत नहीं और मरीज़ की सहमति भी ज़रूरी नहीं।",
      draftConsentDenied:
        "मरीज़ ने AI को अपने रिकॉर्ड देखने की सहमति नहीं दी। खुद नुस्ख़ा लिखें, या मरीज़ से सहमति दिलवाएँ।",
      draftNoDoctorInput:
        "AI मसौदा माँगने से पहले वॉइस नोट, फोटो या टाइप किया हुआ जोड़ संलग्न करें।",
      draftCaseClosed: "यह मामला बंद है, इसलिए नया मसौदा नहीं माँगा जा सकता।",
      draftCaseNotFound:
        "यह मामला नहीं मिल सका। यह बंद हो सकता है या किसी और डॉक्टर को सौंपा गया हो।",
      workingRxLoadFail: "चालू नुस्ख़ा लोड नहीं हो सका।",
      rxItemsLabel: "नुस्ख़े की वस्तुएँ",
      rxNameLabel: "दवा",
      rxDoseLabel: "मात्रा",
      rxDurationLabel: "अवधि",
      rxFrequencyLabel: "आवृत्ति",
      rxEmptyItems: "अभी कोई वस्तु नहीं। नीचे पहली वस्तु जोड़ें।",
      addItemAction: "वस्तु जोड़ें",
      removeItemAction: "हटाएँ",
      saveRevisionAction: "रिवीज़न सहेजें",
      savingRevision: "सहेज रहा है",
      revisionSaved: "रिवीज़न सहेजा गया।",
      saveRevisionFail: "यह रिवीज़न सहेजा नहीं जा सका।",
      sourceLabel: "स्रोत",
      sourceAiDraft: "AI मसौदा",
      sourceManual: "मैनुअल",
      // अनुमोदन/अस्वीकृति/बंद करना (#453, US-19..22): नुस्ख़े पर डॉक्टर का निर्णय
      // और बिना नुस्ख़े के मामला बंद करना।
      rxStatusLabel: "नुस्ख़े की स्थिति",
      rxStatusDraft: "मसौदा",
      rxStatusReviewed: "समीक्षित",
      rxStatusRejected: "अस्वीकृत",
      rxStatusIssued: "जारी हुई",
      rxStatusFulfilled: "पूर्ण हुई",
      decisionHeading: "डॉक्टर का निर्णय",
      editedTracker: (n: number) => `${n} आइटम आपके द्वारा संपादित`,
      // Step 1: Review & approve
      approvalGateTitle: "समीक्षा करें और अनुमोदित करें",
      approvalGateHelp:
        "जारी करने से पहले पुष्टि करें कि आपने हर वस्तु मरीज़ के रिकॉर्ड के अनुसार जाँची है।",
      verificationDeclaration:
        "मैंने यह नुस्ख़ा जाँच लिया है (Maine check kar liya)",
      // Step 2: Confirm issue details
      confirmIssueTitle: "जारी करने का विवरण पुष्टि करें",
      confirmIssueHelp:
        "पुष्टि करने पर, यह नुस्ख़ा मरीज़ को जारी होगा और बदला नहीं जा सकेगा।",
      confirmIssueDeclaration:
        "मैं पुष्टि करता हूँ कि यह नुस्ख़ा सही है और मरीज़ को जारी करने के लिए तैयार है।",
      approveIssueAction: "अनुमोदित करें और जारी करें",
      approvingIssuance: "अनुमोदित हो रहा है",
      approveBlockedHelp:
        "नुस्ख़ा अनुमोदित और जारी करने के लिए दोनों पुष्टियाँ पूरी करें।",
      approveFail: "यह नुस्ख़ा अनुमोदित और जारी नहीं हो सका।",
      issuedHeading: "नुस्ख़ा जारी हुआ",
      issuedImmutableNote: "जारी नुस्ख़ा अंतिम है और बदला नहीं जा सकता।",
      issuedAtLabel: "जारी हुआ",
      issuedAttributedTo: "आपको श्रेय",
      rejectAction: "मसौदा अस्वीकार करें",
      rejectingDraft: "अस्वीकार हो रहा है",
      rejectReasonLabel: "मरीज़ के लिए कारण",
      rejectReasonPlaceholder:
        "सरल भाषा में बताएँ कि यह मसौदा क्यों अनुमोदित नहीं हुआ, ताकि मरीज़ समझ सके।",
      rejectFail: "मसौदा अस्वीकार नहीं हो सका।",
      rejectedHeading: "मसौदा अस्वीकृत",
      rejectedHelp:
        "कारण मरीज़ के लिए दर्ज है। मामला खुला रहता है - आप नया मसौदा माँग सकते हैं या बिना नुस्ख़े के बंद कर सकते हैं।",
      rejectedReasonLabel: "दर्ज कारण",
      closeWithoutRxHeading: "बिना नुस्ख़े के बंद करें",
      closeWithoutRxHelp:
        "जब कोई दवा ज़रूरी न हो तब उपयोग करें। मामला बंद होकर आपकी लंबित सूची से हट जाता है।",
      closeReasonLabel: "बंद करने का कारण",
      closeCaseAction: "मामला बंद करें",
      closingCase: "बंद हो रहा है",
      closeFail: "मामला बंद नहीं हो सका।",
      closeReasons: {
        patientWithdrawn: "मरीज़ ने वापसी ली",
        doctorRejected: "डॉक्टर ने उपचार अस्वीकार किया",
        noShow: "मरीज़ उपस्थित नहीं हुए",
        duplicate: "डुप्लीकेट मुलाक़ात",
      },
    },

    // pick.* सतह - PHASE-8.1 T11 (#449): मरीज़ का डॉक्टर-चुनाव चरण
    // (सुझाया गया विशेषज्ञता, सत्यापित डॉक्टर कार्ड, सहमति शीट, पुष्टि)।
    // सुझाव शुरू-यहाँ से फ़िल्टर है, पूरे चुनाव में बाधा नहीं (US-2/US-3)।
    pick: {
      title: "अपना डॉक्टर चुनें",
      subtitle: "अपना डॉक्टर चुनें जो आपके प्री-सारांश की जाँच करेगा",
      suggestedSpecialtyLabel: "आपके लिए सुझाव",
      suggestionNote: "आप कोई भी सत्यापित डॉक्टर चुन सकते हैं",
      bookCta: "इस डॉक्टर के साथ बुक करें",
      viewProfile: "सत्यापित प्रोफ़ाइल देखें",
      feeNotSet: "फ़ीस निर्धारित नहीं",
      feeLabel: "परामर्श शुल्क",
      credentialsVerified: "प्रमाणपत्र सत्यापित",
      noDoctorsTitle: "कोई डॉक्टर नहीं मिला",
      noDoctorsBody:
        "अभी इस विशेषज्ञता में कोई सत्यापित डॉक्टर उपलब्ध नहीं है।",
      lowConfidenceHint:
        "आपके प्री-सारांश की समीक्षा ज़रूरी है। डॉक्टर चुनने से पहले अपने लक्षण बदल सकते हैं।",
      editSymptoms: "लक्षण बदलें",
      allow: "मंज़ूर करें",
      consentTitle: "अपना प्री-सारांश साझा करना",
      consentScope:
        "यह डॉक्टर आपके लक्षणों का सारांश देखेगा और आपकी देखभाल का मसौदा बनाते समय आपके परामर्श तथा प्रिस्क्रिप्शन रिकॉर्ड देख सकता है।",
      consentValidity: "यह पहुँच तब तक मान्य है जब तक आप इसे रद्द नहीं करते।",
      confirmTitle: "डॉक्टर चुन लिया गया",
      confirmBody: "अब आपका प्री-सारांश केवल इसी डॉक्टर को दिखेगा।",
      whatHappensNext: "आगे क्या होगा",
      whatHappensNextItems:
        "डॉक्टर आपके प्री-सारांश की समीक्षा करेंगे। ज़रूरत पड़ने पर वे परामर्श के लिए संपर्क करेंगे। आप अपनी इनटेक स्थिति से ट्रैक कर सकते हैं।",
      loading: "सत्यापित डॉक्टर खोजे जा रहे हैं…",
      recordingChoice: "आपका चुनाव दर्ज किया जा रहा है…",
      genericError: "कुछ गलत हुआ। फिर से प्रयास करें।",
      viewIntakeStatus: "इनटेक स्थिति देखें",
      errorTitle: "डॉक्टर सूची लोड नहीं हो सकी",
      errorBody: "अपना कनेक्शन जाँचें और फिर से प्रयास करें।",
      retry: "फिर से प्रयास करें",
      breadcrumb: "डॉक्टर चुनें",
    },
    findCare: {
      resumeTitle: "एक परामर्श प्रगति पर है",
      resumeBody:
        "आपका प्री-सारांश तैयार है। डॉक्टर चुनना फिर से शुरू करें जो इसकी जाँच करेगा।",
      bookCta: "परामर्श बुक करें",
    },
  },
};
