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

export type Lang = "en" | "hi";

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

  // staffAuth.* surface - PHASE-2.6 T10 (#201): the split-auth staff entry
  // (/staff/login), partner status screens, and the scoped staff-role picker.
  // Pages only this phase: submits name Phase 5 honestly, never fake success.
  staffAuth: {
    login: {
      brand: "CareSetu",
      subtitle: "Staff sign-in - doctor, lab, chemist and operator",
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
      genericError: "Something went wrong on our side. Please retry.",
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
        mobileInvalid:
          "Enter a valid 10-digit Indian mobile number, or leave this blank.",
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
    },
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
    queue: "Queue",
    cases: "Cases",
    patients: "Patients",
    orders: "Orders",
    history: "History",
    settlements: "Settlements",
    profile: "Profile",
    verifications: "Verifications",
    disputes: "Disputes",
    audit: "Audit",
  },

  // record.* surface - PHASE-3 T7 (#216): the My Record timeline screen
  // (blueprint §5.5, binding prototype record.html). Filter naming follows
  // the ratified review outcome: "Consultations" everywhere incl. Hindi
  // परामर्श - consultation wording, never physical-visit.
  record: {
    title: "My Record",
    description:
      "Your health story in one place - consultations, prescriptions, lab results and daily metrics.",
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
      delivered: "Delivered",
    },
    filedFromBooking: "filed from booking",
    empty: {
      title: "No entries yet",
      body: "Your consultations, prescriptions, lab results and metrics appear here as your care happens.",
    },
    loadError: "Could not load your record.",
    placeholder: {
      accessTitle: "Who accessed my record",
      accessBody: "Full access history arrives with Phase 4.",
      healthTitle: "Health tracking",
      healthBody: "BP/sugar trends and follow-up plans arrive with Phase 12.",
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
};

export type Dictionary = typeof en;
export type AuthStrings = Dictionary["auth"];
export type StaffAuthStrings = Dictionary["staffAuth"];
export type ProfileStrings = Dictionary["profile"];

export const STRINGS: Record<Lang, Dictionary> = {
  en,
  hi: {
    auth: {
      brand: "सेतु",
      tagline: "आपका स्वास्थ्य, जुड़ा हुआ",
      phoneLabel: "मोबाइल नंबर",
      phonePlaceholder: "10 अंकों का मोबाइल नंबर",
      getCode: "वेरिफिकेशन कोड पाएँ",
      verify: "सत्यापित करें",
      resend: "कोड फिर से भेजें",
      backToEdit: "नंबर बदलें",
      codeLabel: "वेरिफिकेशन कोड",
      codeHint: "SMS से भेजा गया 6 अंकों का कोड",
      codeExpires: "कोड समाप्त होने में",
      resendIn: (s) => `${s}s में फिर से भेजें`,
      attemptsLeft: (n) => `${n} प्रयास शेष`,
      noAttempts: "कोई प्रयास नहीं बचा। नया कोड माँगें।",
      wrongCode: (n) => `गलत कोड। ${n} प्रयास शेष।`,
      badPhone: "सही 10 अंकों का भारतीय मोबाइल नंबर दर्ज करें।",
      shortCode: "पूरा 6 अंकों का कोड दर्ज करें।",
      lockout: (m) => `बहुत अधिक गलत प्रयास। ${m} मिनट के लिए लॉक किया गया।`,
      resendEarly: (s) => `कूलडाउन सक्रिय। ${s}s में फिर से भेजें।`,
      expiredOrUsed: "यह कोड समाप्त या उपयोग हो चुका है। नया कोड माँगें।",
      latestWins: "नया कोड भेजा गया। पुराना कोड अब मान्य नहीं है।",
      duplicateNotice:
        "यह नंबर पहले से पंजीकृत है - सत्यापन से आप लॉग इन होंगे।",
      verifiedTitle: "पहचान सत्यापित",
      verifiedBody: "आपका नंबर सत्यापित हो गया और सत्र तैयार है।",
      goHome: "सेतु होम पर जाएँ",
      welcome: "आपकी पूरी स्वास्थ्य यात्रा के लिए एक स्थिर पहचान।",
      stepPhone: "फ़ोन",
      stepVerify: "सत्यापन",
      stepDone: "पूर्ण",
      stepProgress: "साइन इन प्रगति",
      valueProps: [
        "एक स्थिर पहचान - कोई डुप्लीकेट खाता नहीं",
        "आपका रिकॉर्ड आपका है, केवल आपकी सहमति से साझा",
        "हिंदी और अंग्रेज़ी दोनों में",
      ],
      networkError: "सर्वर से संपर्क नहीं हो सका। अपना कनेक्शन जाँचें।",
      smsFailed: "कोड भेजा नहीं जा सका। कुछ देर में फिर कोशिश करें।",
      suspendedNotice: "यह नंबर निलंबित है। सहायता के लिए संपर्क करें।",
      notRegistered: "यह नंबर पंजीकृत नहीं था। वापस जाकर पहले कोड माँगें।",
      sessionTitle: "आप साइन इन हैं",
      sessionBody: "आपकी पहचान सत्यापित है और स्वास्थ्य यात्रा तैयार है।",
      signedInAs: (phone) => `${phone} से साइन इन`,
      signOut: "साइन आउट",
    },
    staffAuth: {
      login: {
        brand: "CareSetu",
        subtitle: "स्टाफ साइन-इन - डॉक्टर, लैब, केमिस्ट और ऑपरेटर",
        heading: "साइन इन करें",
        emailLabel: "ईमेल",
        emailPlaceholder: "you@example.com",
        passwordLabel: "पासवर्ड",
        showPassword: "दिखाएँ",
        hidePassword: "छिपाएँ",
        forgotPassword: "पासवर्ड भूल गए?",
        signIn: "साइन इन करें",
        phoneLabel: "फ़ोन नंबर",
        phonePlaceholder: "10 अंकों का मोबाइल नंबर",
        phoneInvalid: "एक सही फ़ोन नंबर दर्ज करें।",
        mfaCodeLabel: "प्रमाणीकरण कोड (2FA)",
        mfaHelp: "अपने authenticator ऐप से 6 अंकों का कोड दर्ज करें।",
        mfaSubmit: "कोड सत्यापित करें",
        codeRequired: "6 अंकों का कोड दर्ज करें।",
        newHereTitle: "CareSetu पर नए हैं?",
        newHereBody:
          "अपनी प्रैक्टिस या व्यवसाय रजिस्टर करें - लिस्ट होने से पहले हमारी टीम जाँच करती है।",
        registerDoctor: "डॉक्टर",
        registerLab: "लैब",
        registerChemist: "केमिस्ट",
        noRolePickerNote:
          "यहाँ जानबूझकर कोई रोल पिकर नहीं है: साइन इन पर आपका रोल आपके खाते से तय होता है, हाथ से नहीं चुना जाता। मरीज़ फ़ोन OTP विज़ार्ड से साइन इन करते हैं।",
        interimNote: "Phase 5 तक अंतरिम स्टाफ प्रवेश उपलब्ध रहेगा:",
        chooseRoleLink: "रोल चुनें",
        emailInvalid: "एक सही ईमेल पता दर्ज करें।",
        passwordRequired: "अपना पासवर्ड दर्ज करें।",
        summaryTitle: (n) => `आगे बढ़ने से पहले ${n} फ़ील्ड में ध्यान देना है।`,
        phase5Notice:
          "साइन-इन अभी जुड़ा नहीं है: स्टाफ प्रमाणीकरण Phase 5 में आएगा। अभी कुछ भेजा या सहेजा नहीं गया।",
        invalidCredentials: "ईमेल या पासवर्ड गलत है।",
        accountLocked:
          "बार-बार विफल प्रयासों के बाद यह खाता अस्थायी रूप से लॉक है। लगभग 15 मिनट बाद फिर कोशिश करें या पासवर्ड रीसेट करें।",
        genericError: "हमारी तरफ़ से कुछ गड़बड़ हुई। कृपया फिर से कोशिश करें।",
      },
      pending: {
        badge: "जाँच प्रक्रिया में",
        headerTitle: "आवेदन की स्थिति",
        title: "आपका आवेदन जाँचा जा रहा है",
        submittedLabel: "जमा किया गया",
        applicationLabel: "आवेदन",
        verifyingLabel: "जिसकी जाँच हो रही है",
        windowLabel: "समीक्षा अपेक्षित अवधि",
        detailPlaceholder: "स्टाफ खाते लाइव होने पर दिखेगा (Phase 5)",
        windowValue: "48 घंटे के भीतर",
        infoBanner:
          "सक्रिय होने तक आप सार्वजनिक रूप से सूचीबद्ध नहीं होंगे। यदि कुछ और चाहिए तो हम आपको कॉल या संदेश भेजेंगे।",
        helpCta: "सहायता: CareSetu टीम से संपर्क करें",
        loadError:
          "आपकी आवेदन स्थिति लोड नहीं हो सकी। कृपया अपना कनेक्शन जाँचें और फिर से प्रयास करें।",
      },
      rejected: {
        badge: "अस्वीकृत",
        headerTitle: "आवेदन की स्थिति",
        title: "हम आपका आवेदन सत्यापित नहीं कर सके",
        reasonHeading: "कारण:",
        reasonPlaceholder:
          "ऑपरेटर समीक्षा लाइव होने पर विशिष्ट कारण यहाँ दिखेगा (Phase 5)।",
        fixNote:
          "समस्या ठीक करें और फिर से जमा करें - आपका संशोधित अपलोड सीधे जाँच में वापस चला जाएगा; आप शुरुआत से नहीं करते।",
        resubmitCta: "दोबारा अपलोड करें और जमा करें",
        resubmitStubNotice:
          "दोबारा जमा करना Phase 5 के साथ खुलेगा - अभी कुछ भी दोबारा जमा नहीं हुआ।",
        helpCta: "सहायता: CareSetu टीम से संपर्क करें",
        loadError:
          "आपकी अस्वीकृति विवरण लोड नहीं हो सका। कृपया अपना कनेक्शन जाँचें और फिर से प्रयास करें।",
        appealProcessing: "आपकी अपील जमा हो रही है...",
        appealSuccess: "अपील जमा हो गई। आप फिर से सत्यापन कतार में हैं।",
      },
      picker: {
        title: "जारी रखने के लिए एक रोल चुनें",
        sub: "इस खाते में एक से अधिक स्टाफ रोल हैं। कौन-सा कंसोल खोलना है चुनें - बाद में ऊपरी बार से बदल सकते हैं।",
        doctorDesc: "कतार, केस, मरीज़, प्रोफ़ाइल",
        partnerDesc: "ऑर्डर, इतिहास, सेटलमेंट, प्रोफ़ाइल",
        operatorDesc: "सत्यापन, विवाद, ऑडिट",
      },

      register: {
        subtitle:
          "अभी आवेदन करें - लिस्ट होने से पहले हमारी टीम हर दस्तावेज़ जाँचती है।",
        stepperLabel: "पंजीकरण चरण",
        steps: [
          "खाते की मूल जानकारी",
          "पहचान",
          "दस्तावेज़",
          "समीक्षा और घोषणाएँ",
        ],
        typeBadge: {
          doctor: "डॉक्टर आवेदन",
          lab: "लैब आवेदन",
          chemist: "केमिस्ट आवेदन",
        },
        typeLabels: { doctor: "डॉक्टर", lab: "लैब", chemist: "केमिस्ट" },
        back: "वापस",
        continueCta: "आगे बढ़ें",
        submitApplication: "आवेदन जमा करें",
        summaryTitle: (n) => `जारी रखने से पहले ${n} फ़ील्ड में ध्यान देना है।`,
        accountTitle: "खाते की मूल जानकारी",
        identityTitleDoctor: "प्रोफ़ेशनल पहचान",
        identityTitlePartner: "व्यवसाय की पहचान",
        credentialsTitle: "दस्तावेज़ अपलोड",
        credentialsNote:
          "फ़ोटो या PDF। फ़ाइलें हमारी टीम जाँचती है; सक्रिय होने तक कुछ भी सार्वजनिक रूप से नहीं दिखता।",
        reviewTitle: "समीक्षा और घोषणाएँ",
        fields: {
          fullName: "पूरा नाम",
          fullNamePlaceholder: "जैसे डॉ. आशा कुमार",
          email: "ईमेल",
          emailPlaceholder: "you@example.com",
          password: "पासवर्ड",
          passwordHelp:
            "मज़बूती: 12+ अक्षरों में एक अंक और एक प्रतीक के साथ बनाएँ।",
          mobile: "सूचनाओं के लिए मोबाइल",
          mobilePlaceholder: "10 अंकों का मोबाइल नंबर",
          degreeName: "डिग्री के अनुसार नाम",
          degreeNamePlaceholder: "प्रमाणपत्र पर जैसा छपा है वैसा ही",
          council: "राज्य मेडिकल काउंसिल",
          councilPlaceholder: "अपनी काउंसिल चुनें",
          city: "शहर",
          cityPlaceholder: "जैसे डालटनगंज",
          languages: "बोली जाने वाली भाषाएँ",
          languagesPlaceholder: "जैसे हिंदी, English",
          businessName: "व्यवसाय का नाम",
          address: "पता",
          serviceArea: "सेवा क्षेत्र",
          serviceAreaPlaceholder: "जैसे डालटनगंज + 15 किमी",
          ownerContact: "मालिक का संपर्क",
        },
        optionalSuffix: "(वैकल्पिक)",
        mobilePrefix: "+91",
        councils: [
          "झारखंड राज्य मेडिकल काउंसिल",
          "बिहार राज्य मेडिकल काउंसिल",
          "अन्य",
        ],
        slots: {
          councilCert: {
            label: "राज्य मेडिकल काउंसिल पंजीकरण प्रमाणपत्र",
            hint: "फ़ोटो/PDF अपलोड करें",
          },
          degrees: {
            label: "डिग्री प्रमाणपत्र (MBBS / MD)",
            hint: "फ़ोटो/PDF अपलोड करें",
          },
          photoId: { label: "सरकारी फ़ोटो ID", hint: "आधार / पैन / DL" },
          businessReg: {
            label: "व्यवसाय पंजीकरण",
            hint: "GST / ट्रेड लाइसेंस",
          },
          accreditations: { label: "मान्यताएँ", hint: "NABL / ISO हो तो" },
          kyc: { label: "मालिक का KYC", hint: "सरकारी फ़ोटो ID" },
          drugLicense: {
            label: "ड्रग लाइसेंस (फ़ॉर्म 20/21)",
            hint: "फ़ोटो/PDF अपलोड करें",
          },
          shopLicense: {
            label: "दुकान लाइसेंस",
            hint: "नगर पालिका ट्रेड लाइसेंस",
          },
        },
        uploadPrompt: "फ़ोटो/PDF अपलोड करें",
        removeFile: "हटाएँ",
        review: {
          applicant: "आवेदक",
          email: "ईमेल",
          mobile: "सूचनाओं के लिए मोबाइल",
          notProvided: "नहीं दिया गया",
          type: "प्रकार",
          credentialsAttached: "संलग्न दस्तावेज़",
          fileCount: (n) => `${n} ${n === 1 ? "फ़ाइल" : "फ़ाइलें"}`,
          noFile: "कुछ संलग्न नहीं",
        },
        declarations: {
          truth:
            "मैं घोषणा करता/करती हूँ कि दी गई जानकारी और दस्तावेज़ सही हैं।",
          consent:
            "मैं CareSetu द्वारा दस्तावेज़ सत्यापन की सहमति देता/देती हूँ।",
          terms: "मैं सेवा की शर्तें स्वीकार करता/करती हूँ।",
        },
        errors: {
          fullNameRequired: "अपना पूरा नाम दर्ज करें।",
          emailInvalid: "एक सही ईमेल पता दर्ज करें।",
          passwordWeak:
            "कम से कम 12 अक्षर, जिसमें एक अंक और एक प्रतीक हो, इस्तेमाल करें।",
          mobileInvalid:
            "सही 10 अंकों का भारतीय मोबाइल नंबर दर्ज करें, या खाली छोड़ दें।",
          degreeNameRequired: "डिग्री के अनुसार नाम दर्ज करें।",
          councilRequired: "अपनी राज्य मेडिकल काउंसिल चुनें।",
          cityRequired: "अपना शहर दर्ज करें।",
          languagesRequired: "मरीज़ों से बोली जाने वाली भाषाएँ दर्ज करें।",
          businessNameRequired: "व्यवसाय का नाम दर्ज करें।",
          addressRequired: "व्यवसाय का पता दर्ज करें।",
          serviceAreaRequired: "अपना सेवा क्षेत्र दर्ज करें।",
          ownerContactInvalid:
            "मालिक का सही 10 अंकों का भारतीय मोबाइल नंबर दर्ज करें।",
          uploadRequired: "जारी रखने के लिए यह दस्तावेज़ संलग्न करें।",
          uploadWrongType:
            "यहाँ केवल फ़ोटो (JPEG, PNG, WebP) या PDF फ़ाइलें चलेंगी।",
          uploadTooLarge: "फ़ाइलें 10 MB या उससे छोटी होनी चाहिए।",
          declarationRequired: "आगे बढ़ने के लिए यह घोषणा टिक करें।",
        },
        phase5Notice:
          "जमा करना अभी जुड़ा नहीं है: आवेदन Phase 5 में आएँगे। अभी कुछ भेजा या सहेजा नहीं गया।",
      },
    },
    consent: {
      title: "साझा करने की अनुमति",
      whoLabel: "कौन पूछ रहा है",
      whatLabel: "वे क्या देखेंगे",
      howLongLabel: "कितने समय के लिए",
      verifiedBadge: "सत्यापित",
      allow: "अनुमति दें",
      deny: "अभी नहीं",
      logLink: "सभी अनुमतियाँ देखें",
      grantedNote: "अनुमति मिल गई - आपके अनुमति लॉग में दर्ज हुई।",
      deniedNote:
        "कोई बात नहीं। अनुमति के बिना लैब आपका इतिहास इस बुकिंग से नहीं जोड़ पाएगा - बुकिंग फिर भी हो सकती है, बस रिकॉर्ड साझा नहीं होगा।",
      demo: {
        badge: "डेमो केयर एक्शन",
        cardTitle: "लैब टेस्ट बुक करें",
        cardBody:
          "यह बुकिंग आपका हाल का रिकॉर्ड जोड़ना चाहती है ताकि डॉक्टर को संदर्भ मिले। आपकी अनुमति के बिना कुछ साझा नहीं होता।",
        cta: "बुकिंग जारी रखें",
        requesterName: "सहयोग पैथ लैब",
        requesterContext: "आपकी बुकिंग के माध्यम से · डॉ. ए. कुमार का रेफ़रंस",
        scope: "आपकी पिछले 3 महीने की प्रिस्क्रिप्शन",
        validity:
          "सिर्फ़ इसी बुकिंग के लिए। आप मेरा रिकॉर्ड → अनुमति लॉग से कभी भी वापस ले सकते हैं।",
        allowedProceed: "आपकी बुकिंग जारी है - आपका रिकॉर्ड जुड़ गया।",
        standingDenial: "आपने पहले 'अभी नहीं' चुना था - कुछ भी साझा नहीं हुआ।",
      },
    },
    profile: {
      title: "स्वागत है! प्रोफ़ाइल पूरी करें",
      sub: "तीन छोटे कदम। ज़रूरी नहीं वाले कदम छोड़ भी सकते हैं।",
      pageTitle: "अपनी प्रोफ़ाइल पूरी करें",
      steps: ["ज़रूरी", "वैकल्पिक", "वैकल्पिक"],
      s1: "आपके बारे में",
      s2: "हेल्थ ट्रैकिंग (ऐच्छिक)",
      s2sub:
        "ब्लड प्रेशर या शुगर की रोज़ एंट्री चालू करें - हम धीरे-धीरे याद दिलाएँगे।",
      s3: "संपर्क और फ़ोटो (ऐच्छिक)",
      name: "पूरा नाम",
      namePlaceholder: "जैसे आशा देवी",
      age: "उम्र",
      agePlaceholder: "साल",
      gender: "लिंग",
      genderPlaceholder: "चुनें",
      genders: { female: "महिला", male: "पुरुष", other: "अन्य" },
      langLabel: "भाषा पसंद",
      bp: "ब्लड प्रेशर",
      sugar: "ब्लड शुगर",
      photo: "प्रोफ़ाइल फ़ोटो",
      photoPrompt: "फ़ोटो अपलोड करें",
      area: "इलाक़ा / पता",
      areaPlaceholder: "वार्ड, मोहल्ला, पहचान",
      ec: "आपातकालीन संपर्क",
      ecPlaceholder: "+91",
      skip: "अभी नहीं",
      continueCta: "आगे बढ़ें",
      finish: "पूरा करें",
      meterLabel: "प्रोफ़ाइल पूरी",
      errors: {
        nameRequired: "अपना पूरा नाम दर्ज करें।",
        ageRequired: "अपनी उम्र दर्ज करें।",
        ageInvalid: "पूरी संख्या में 1 से 120 के बीच उम्र दर्ज करें।",
        genderRequired: "अपना लिंग चुनें।",
      },
      nudges: {
        basicsTitle: "विज़िट शुरू करने के लिए नाम जोड़ें",
        basicsBody:
          "इलाज से जुड़े कामों के लिए नाम वाला रिकॉर्ड ज़रूरी है - एक मिनट लगेगा।",
        trackingTitle: "हेल्थ ट्रैकिंग चालू करें",
        trackingBody:
          "ब्लड प्रेशर या शुगर की रोज़ एंट्री से धीमे-धीमे याद-दिलाने वाले कार्ड मिलेंगे।",
        photoTitle: "प्रोफ़ाइल फ़ोटो जोड़ें",
        photoBody:
          "इससे प्रोवाइडर पक्का कर पाते हैं कि वे सही व्यक्ति का इलाज कर रहे हैं।",
        areaTitle: "दवाई डिलीवरी के लिए अपना इलाक़ा जोड़ें",
        areaBody: "डिलीवरी चेकआउट के लिए इलाक़ा या पता ज़रूरी है।",
        emergencyTitle: "आपातकालीन संपर्क जोड़ें",
        emergencyBody:
          "एक फ़ोन नंबर जिससे हम किसी आपात स्थिति में संपर्क कर सकें।",
        dismiss: "हटाएँ",
        completeCta: "प्रोफ़ाइल पूरी करें",
      },
      gate: {
        basicsExplain:
          "इलाज से जुड़े कामों के लिए नाम वाला रिकॉर्ड (नाम, उम्र, लिंग) ज़रूरी है - जारी रखने के लिए यहाँ जोड़ें।",
        areaExplain:
          "दवाई डिलीवरी के लिए आपका इलाक़ा या पता ज़रूरी है - जारी रखने के लिए यहाँ जोड़ें।",
      },
      demo: {
        badge: "डेमो केयर एक्शन",
        title: "केयर-एक्शन गेटिंग",
        body: "Find Care और My Record देखना कभी गेट नहीं होता। केयर एक्शन पर आपकी प्रोफ़ाइल उसी समय जाँची जाती है:",
        intake: "विज़िट शुरू करें (इंटेक)",
        booking: "अपॉइंटमेंट बुक करें",
        checkout: "दवाई डिलीवरी - चेकआउट पर जाएँ",
        proceedNote:
          "यह एक्शन गेटिंग पार करता है - असली इंटेक/बुकिंग/चेकआउट फ़्लो अपने बिल्ड फ़ेज़ में आएँगे।",
      },
    },

    nav: {
      home: "होम",
      find: "खोजें",
      start: "शुरू करें",
      record: "मेरा रिकॉर्ड",
      inbox: "इनबॉक्स",
      bookings: "बुकिंग और ऑर्डर",
      profileSettings: "प्रोफ़ाइल और सेटिंग",
      more: "और",
      queue: "कतार",
      cases: "केस",
      patients: "मरीज़",
      orders: "ऑर्डर",
      history: "इतिहास",
      settlements: "सेटलमेंट",
      profile: "प्रोफ़ाइल",
      verifications: "सत्यापन",
      disputes: "विवाद",
      audit: "ऑडिट",
    },
    home: {
      nav: {
        doctors: "डॉक्टर",
        labs: "लैब",
        chemists: "केमिस्ट",
      },
      authButton: {
        login: "लॉगिन",
        dashboard: "डैशबोर्ड",
      },
      hero: {
        h1: "अपने आसपास भरोसेमंद डॉक्टर, लैब और केमिस्ट खोजें",
        sub: "अपॉइंटमेंट लें, रिपोर्ट साझा करें और हर रिकॉर्ड एक जगह रखें - सिर्फ़ आपकी सहमति से।",
        typeLabel: "प्रोवाइडर प्रकार",
        typeDoctor: "डॉक्टर",
        typeLab: "लैब",
        typeChemist: "केमिस्ट",
        searchPlaceholder: "नाम, विशेषज्ञता या जाँच से खोजें",
        locationLabel: "स्थान",
        cta: "खोजें",
        getStarted: "शुरू करें",
      },
      chips: {
        title: "आम ज़रूरतें",
        generalPhysician: "जनरल फ़िज़िशियन",
        pediatrician: "बाल रोग विशेषज्ञ",
        gynecologist: "स्त्री रोग विशेषज्ञ",
        dentist: "दंत चिकित्सक",
        bloodTest: "खून जाँच",
        xRay: "एक्स-रे",
        fullBodyCheckup: "फुल बॉडी चेकअप",
        medicineDelivery: "दवाई डिलीवरी",
      },
      tiles: {
        title: "श्रेणी से खोजें",
        doctorsSub: "जनरल फ़िज़िशियन, बाल रोग, स्त्री रोग, दंत",
        labsSub: "खून जाँच, एक्स-रे, फुल बॉडी चेकअप",
        chemistsSub: "ई-प्रिस्क्रिप्शन से दवाई डिलीवरी",
      },
      featured: {
        title: "चुनिंदा डॉक्टर",
        viewAll: "सभी डॉक्टर देखें",
        verified: "सत्यापित",
        emptyTitle: "डालटनगंज में डायरेक्टरी जल्द आ रही है",
        emptyBody:
          "लिस्ट होने से पहले हम हर प्रोवाइडर की जाँच करते हैं। जाँच पूरी होने तक कोई डॉक्टर नहीं दिखता।",
        emptyCta: "मरीज़ के तौर पर शुरू करें",
      },
      how: {
        title: "CareSetu कैसे काम करता है",
        s1t: "प्रोवाइडर खोजें",
        s1b: "आसपास के जाँचे-परखे डॉक्टर, लैब और केमिस्ट खोजें।",
        s2t: "आवाज़ में बताएँ तकलीफ़",
        s2b: "AI एक ड्राफ़्ट सारांश बनाता है - आगे बढ़ने से पहले आपका डॉक्टर हमेशा उसे जाँचता है।",
        s3t: "सब एक जगह रहता है",
        s3b: "प्रिस्क्रिप्शन, रिपोर्ट और रिकॉर्ड आपके हेल्थ रिकॉर्ड में - सिर्फ़ आपकी सहमति से साझा।",
      },
      trust: {
        t1: "लिस्टिंग से पहले दस्तावेज़ जाँचे जाते हैं",
        t2: "आपकी सहमति के बिना कुछ साझा नहीं होता",
        t3: "आपके रिकॉर्ड, आपका नियंत्रण - कभी भी वापस ले सकते हैं",
        privacy: "प्राइवेसी और शर्तें",
      },
      providers: {
        title: "क्या आप प्रोवाइडर हैं?",
        sub: "अभी रजिस्टर करें - लिस्ट होने से पहले हमारी टीम जाँच करती है।",
        doctorT: "आप डॉक्टर हैं?",
        doctorB:
          "अपने शहर में जाँचे-परखे इलाज की तलाश करने वाले मरीज़ों तक पहुँचें।",
        labT: "लैब चलाते हैं?",
        labB: "बुक किए गए टेस्ट ऑर्डर पाएँ और रिपोर्ट डिजिटल तरीके से भेजें।",
        chemistT: "केमिस्ट की दुकान है?",
        chemistB: "मंज़ूर ई-प्रिस्क्रिप्शन भरें और अपनी दुकान बढ़ाएँ।",
        register: "रजिस्टर करें",
      },
      finalCta: {
        title: "अपने हेल्थ रिकॉर्ड से शुरू करें",
        sub: "एक मुफ़्त खाता रिकॉर्ड, बुकिंग और ऑर्डर सब एक साथ रखता है।",
      },
      footer: {
        patients: "मरीज़",
        providersCol: "प्रोवाइडर",
        companyLegal: "कंपनी और कानूनी",
        findDoctors: "डॉक्टर खोजें",
        findLabs: "लैब खोजें",
        findChemists: "केमिस्ट खोजें",
        howItWorks: "यह कैसे काम करता है",
        regDoctor: "डॉक्टर के रूप में रजिस्टर",
        regLab: "लैब के रूप में रजिस्टर",
        regChemist: "केमिस्ट के रूप में रजिस्टर",
        staffLogin: "स्टाफ लॉगिन",
        about: "हमारे बारे में",
        privacy: "प्राइवेसी",
        terms: "शर्तें",
        contact: "संपर्क",
        meta: "\u00a9 CareSetu - डालटनगंज और आसपास के इलाक़ों में",
        operatorConsole: "ऑपरेटर कंसोल",
      },
    },

    record: {
      title: "मेरा रिकॉर्ड",
      description:
        "आपकी सेहत की पूरी कहानी एक जगह - परामर्श, प्रिस्क्रिप्शन, लैब रिपोर्ट और रोज़ की मेट्रिक्स।",
      filterGroupLabel: "रिकॉर्ड एंट्री फ़िल्टर करें",
      moreMenuLabel: "और फ़िल्टर",
      filter: {
        all: "सभी",
        consultation: "परामर्श",
        prescription: "प्रिस्क्रिप्शन",
        labReport: "लैब रिपोर्ट",
        metric: "मेट्रिक्स",
        more: "और",
      },
      badge: {
        consultation: "परामर्श",
        prescription: "प्रिस्क्रिप्शन",
        labReport: "लैब रिपोर्ट",
        metric: "मेट्रिक",
        settlement: "सेटलमेंट",
        issued: "जारी हुई",
        delivered: "पहुँच गई",
      },
      filedFromBooking: "बुकिंग से दर्ज",
      empty: {
        title: "अभी कोई एंट्री नहीं",
        body: "आपके परामर्श, प्रिस्क्रिप्शन, लैब रिपोर्ट और मेट्रिक्स यहाँ दिखेंगे जैसे-जैसे आपकी देखभाल होगी।",
      },
      loadError: "आपका रिकॉर्ड लोड नहीं हो सका।",
      placeholder: {
        accessTitle: "रिकॉर्ड किसने देखा",
        accessBody: "पूरा एक्सेस इतिहास फेज़ 4 में आएगा।",
        healthTitle: "हेल्थ ट्रैकिंग",
        healthBody: "BP/शुगर ट्रेंड और फॉलो-अप प्लान फेज़ 12 में आएंगे।",
      },
      detail: {
        loadError: "यह एंट्री लोड नहीं हो सकी।",
        notFound: "एंट्री नहीं मिली।",
        filedOn: "दर्ज हुई",
        bookingRef: "बुकिंग",
        sourceHeading: "स्रोत",
        verified: "सत्यापित",
        consentHeading: "अनुमति का हवाला",
        consentLine: (lineageRef: string, version: number, date: string) =>
          `यह रिपोर्ट अनुमति #${lineageRef} v${version} के तहत आपके रिकॉर्ड में आई, अनुमति मिली ${date}।`,
        consentLink: "यह अनुमति अनुमति लॉग में देखें",
        resultsHeading: "नतीजे",
        resultsThTest: "जाँच",
        resultsThValue: "मान",
        resultsThRange: "आम रेंज",
        resultsThStatus: "स्थिति",
        resultsNote:
          "मान वैसे ही दिखाए जाते हैं जैसे लैब ने दर्ज किए। आपका डॉक्टर पूरे संदर्भ में पढ़ता है - ऐप नतीजों की स्वयं व्याख्या नहीं करता।",
        resultsStatusInRange: "रेंज में",
        resultsStatusBelowRange: "रेंज से कम",
        resultsStatusAboveRange: "रेंज से ज़्यादा",
        egressHeading: "इस एंट्री को किसने देखा",
        shareEntry: "यह एंट्री साझा करें",
        downloadPdf: "PDF डाउनलोड करें",
      },
    },
    consentLog: {
      title: "अनुमति लॉग",
      description: "आपने जो अनुमति दी या वापस ली - हर एक की अपनी रसीद।",
      pendingHeading: "आपके जवाब की ज़रूरत",
      historyHeading: "पहले की अनुमतियाँ",
      badge: {
        requested: "अनुरोध आया",
        active: "सक्रिय",
        revoked: "वापस ली",
      },
      viewReceipt: "रसीद देखें",
      metaRequested: "अनुरोध",
      metaGranted: "अनुमति मिली",
      receiptRequested: "{date} पर अनुरोध किया गया।",
      receiptGranted: "{date} पर अनुमति दी गई।",
      receiptRevoked:
        "{date} को वापस ले ली गई - आगे का कोई इस्तेमाल तुरंत रुक गया।",
      allow: "अनुमति दें",
      decline: "अभी नहीं",
      revoke: "वापस लें",
      stopForward:
        "वापसी से पहले देखी गई जानकारी मिटती नहीं। इस अनुमति के तहत जो डेटा इस पार्टनर को मिला, वह उनके पास रहता है।",
      revokeConfirm: {
        title: "यह अनुमति वापस लेनी है?",
        body: "साझा करना तुरंत रुक जाएगा - पार्टनर की आगे की पहुँच बंद। जो पहले देखा या भेजा जा चुका है, वह उनकी रिटेंशन ज़िम्मेदारी के तहत उनके पास रहेगा। आप बाद में ऐसी अनुमति फिर दे सकते हैं (वह नए वर्ज़न के रूप में दर्ज होगी)।",
        confirm: "हाँ, वापस लें",
        cancel: "रहने दें",
        done: "अनुमति वापस ले ली गई - आगे की साझेदारी बंद।",
      },
      egress: {
        heading: "आपके रिकॉर्ड से क्या निकला",
        description:
          "जब भी आपके रिकॉर्ड की कोई चीज़ पढ़ी या भेजी गई, यहाँ दर्ज है - कौन, कब, किस अनुमति में।",
        th: {
          when: "कब",
          what: "क्या",
          to: "किसे",
          via: "किस अनुमति में",
        },
      },
      empty: {
        title: "अभी कोई अनुमति इतिहास नहीं",
        body: "जैसे-जैसे आप अपने रिकॉर्ड की पहुँच साझा या प्रतिबंधित करेंगे, अनुमति इंटरैक्शन यहाँ दिखेंगे।",
      },
      loadError: "आपका अनुमति लॉग लोड नहीं हो सका।",
    },
  },
};
