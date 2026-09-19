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
    specialties: {
      generalPhysician: "General Physician",
      pediatrician: "Pediatrician",
      gynecologist: "Gynecologist",
      dentist: "Dentist",
    },
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
    specialtyLabel: "Specialty",
    areaLabel: "Service area",
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
    placeholder: {
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
  // landing page. Two stacked sections: review queue (low-confidence first,
  // oldest-first within each group) and open care cases, plus the fee editor,
  // coming-soon patients/profile, and a retry path on load failure. All copy
  // bilingual en/hi (REQ-006).
  doctorConsole: {
    title: "Doctor console",
    consoleDescription: "Your review queue and open cases",
    queueHeading: "Review queue",
    queueEmpty: "No pre-summaries waiting for review",
    queueItemMeta: (id: number) => `Intake #${id}`,
    caseItemMeta: (id: number) => `Case #${id}`,
    verifyChip: "Verify",
    confidenceLabel: "Confidence",
    waitingFor: (time: string) => `Waiting ${time}`,
    reviewAction: "Review",
    casesHeading: "Open cases",
    casesEmpty: "No open care cases",
    casesIndexTitle: "My cases",
    casesIndexDescription: "Your open care cases",
    stagePreSummary: "Pre-summary",
    stagePrescriptionPending: "Prescription pending",
    stageClosed: "Closed",
    openCaseAction: "Open",
    feeEditorHeading: "Consultation fee",
    feeEditorHelp:
      "Set the fee patients see when choosing you. Leave blank until set.",
    feeFieldLabel: "Fee (\u20B9)",
    feeFieldPlaceholder: "e.g. 400",
    saveFee: "Save fee",
    clearFee: "Clear fee",
    feeSaved: "Fee saved.",
    feeSaveFailed: "Could not save the fee.",
    patientsComingSoon: "Patients - coming soon",
    profileComingSoon: "Profile - coming soon",
    comingSoonBody: "This area opens in a later update.",
    loadFailed: "Could not load the console.",
    retry: "Try again",
  },

  // caseWorkspace.* surface - PHASE-8.1 T13/T14 (#451/#452): the case
  // workspace. Serves both the review-entry (queue -> review/[intakeId]) and
  // the case-entry (open cases -> cases/[caseId]) routes: case stage chip, the
  // forced-review requirement, the full pre-summary content, the patient's
  // consented health history, the single-action attributed review+finalize,
  // and the consult-complete handshake into prescription-pending (US-13/14/16/
  // 17/24). Prescription drafting (US-18/#452) covers the AI-draft request,
  // the editable rx-item rows, save-revision, and reload of the in-progress
  // working revision; approval/rejection/close are built by #453.
  caseWorkspace: {
    title: "Case workspace",
    backToConsole: "Back to console",
    stageLabel: "Stage",
    forcedReviewChip: "Review required",
    forcedReviewDetail:
      "This pre-summary has low confidence and needs your review before any prescription.",
    summaryHeading: "Pre-summary to review",
    confidenceLabel: "Confidence",
    chiefComplaintsLabel: "Chief complaints",
    symptomsLabel: "Symptoms",
    durationLabel: "Duration",
    durationNotSet: "Not captured",
    patientEditsLabel: "Patient edits",
    patientEditsNone: "No patient edits",
    reviewStateLabel: "Review state",
    reviewStateDraft: "Awaiting your review",
    reviewStateReviewed: "Reviewed",
    reviewStateFinal: "Finalized",
    attributionLabel: "Attributed to",
    reviewedOnLabel: "Reviewed on",
    notReviewedYet: "Not yet attributed",
    historyHeading: "Patient history",
    historyConsentNote: "Only what the patient consented to share.",
    historyEmpty: "No history yet.",
    historyLoadFail: "Could not load patient history.",
    // PHASE-8.1 #484: case workspace inner tabs + original transcript + audio.
    tabPreSummary: "Pre-summary",
    tabHistory: "History",
    tabPrescription: "Prescription",
    transcriptHeading: "Original intake",
    transcriptEmpty: "No transcript available for this intake.",
    transcriptLoadFail: "Could not load the intake transcript.",
    audioPlayLabel: "Play recording",
    audioLoadFail: "Could not load the recording.",
    loadFailed: "Could not load this case workspace.",
    retry: "Try again",
    finalizeAction: "Finalize + attribute review",
    finalizeHelp:
      "One action records your review and finalizes the pre-summary.",
    finalizeSuccess: "Pre-summary finalized and attributed to you.",
    finalizeFail: "Could not finalize this pre-summary.",
    handshakeAction: "Complete consultation",
    handshakeHelp: "Moves the case to prescription pending.",
    handshakeFail: "Could not complete the consultation.",
    handshakeSuccess:
      "Consultation complete - the case is now prescription pending.",
    prescriptionPendingCta: "The prescription editor is ready below.",
    // PHASE-8.1 #484: prescription tab stage lock - the case must consult
    // before any prescription. Pre-summary is always finalized on a born case;
    // the pending item is the consult-complete handshake, and the action jumps
    // to the pre-summary tab where the handshake form lives.
    rxLockTitle: "Prescription not yet open",
    rxLockDone: "Pre-summary finalized",
    rxLockPending: "Consult marked complete",
    rxLockAction: "Complete consultation",
    prescriptionHeading: "Prescription",
    prescriptionHelp:
      "Request an AI draft, then edit the items to match your clinical judgment before saving.",
    requestDraftAction: "Request AI draft",
    requestingDraft: "Requesting",
    requestDraftFail: "Could not generate the AI draft.",
    draftCapReached:
      "The AI drafting limit for this case has been reached. Edit and save the current draft instead.",
    noDraftYet:
      "No prescription draft yet. Request an AI draft to get started.",
    workingRxLoadFail: "Could not load the in-progress prescription.",
    rxItemsLabel: "Prescription items",
    rxNameLabel: "Medicine",
    rxDoseLabel: "Dose",
    rxDurationLabel: "Duration",
    rxFrequencyLabel: "Frequency",
    rxEmptyItems: "No items yet. Add the first one below.",
    addItemAction: "Add item",
    removeItemAction: "Remove",
    saveRevisionAction: "Save revision",
    savingRevision: "Saving",
    revisionSaved: "Revision saved.",
    saveRevisionFail: "Could not save this revision.",
    sourceLabel: "Source",
    sourceAiDraft: "AI draft",
    sourceManual: "Manual",
    // Approval/rejection/close (#453, US-19..22): the review decision on the
    // prescription plus close-without-prescription for the case.
    rxStatusLabel: "Prescription status",
    rxStatusDraft: "Draft",
    rxStatusReviewed: "Reviewed",
    rxStatusRejected: "Rejected",
    rxStatusIssued: "Issued",
    rxStatusFulfilled: "Fulfilled",
    decisionHeading: "Doctor decision",
    editedTracker: (n: number) =>
      n === 1 ? "1 item edited by you" : `${n} items edited by you`,
    approvalGateTitle: "Review & approve",
    approvalGateHelp:
      "Confirm you reviewed every item against the patient record before issuing.",
    verificationDeclaration:
      "I have reviewed this prescription (Maine check kar liya)",
    approveIssueAction: "Approve & issue",
    approvingIssuance: "Approving",
    approveBlockedHelp:
      "Tick the verification declaration to approve and issue the prescription.",
    approveFail: "Could not approve and issue this prescription.",
    issuedHeading: "Prescription issued",
    issuedImmutableNote:
      "The issued prescription is final and cannot be changed.",
    issuedAtLabel: "Issued on",
    issuedAttributedTo: "Attributed to you",
    rejectAction: "Reject draft",
    rejectingDraft: "Rejecting",
    rejectReasonLabel: "Reason for the patient",
    rejectReasonPlaceholder:
      "Explain in plain language why this draft was not approved, so the patient understands.",
    rejectFail: "Could not reject the draft.",
    rejectedHeading: "Draft rejected",
    rejectedHelp:
      "The reason is recorded for the patient. The case stays open - you can request a new draft or close without prescribing.",
    rejectedReasonLabel: "Recorded reason",
    closeWithoutRxHeading: "Close without prescription",
    closeWithoutRxHelp:
      "Use when no medicine is needed. The case moves to Closed and leaves your pending list.",
    closeReasonLabel: "Close reason",
    closeCaseAction: "Close case",
    closingCase: "Closing",
    closeFail: "Could not close the case.",
    closeReasons: {
      patientWithdrawn: "Patient withdrew",
      doctorRejected: "Doctor declined treatment",
      noShow: "Patient did not show up",
      duplicate: "Duplicate visit",
    },
  },

  // pick.* surface - PHASE-8.1 T11 (#449): the patient pick-a-doctor step
  // (suggested specialty, verified doctor cards, consent sheet, confirmation).
  // Suggested specialty is a start-here filter, not blocking choice (US-2/US-3).
  pick: {
    title: "Choose your doctor",
    subtitle: "Pick the doctor who will review your pre-summary",
    suggestedSpecialtyLabel: "Suggested for you",
    suggestionNote: "You can choose any verified doctor",
    bookCta: "Book with this doctor",
    viewProfile: "View verified profile",
    feeNotSet: "Fee not set",
    feeLabel: "Consultation fee",
    credentialsVerified: "Credentials verified",
    noDoctorsTitle: "No doctors found",
    noDoctorsBody:
      "There are no verified doctors available for this specialty right now.",
    lowConfidenceHint:
      "Your pre-summary needs review. You can edit your symptoms before choosing a doctor.",
    editSymptoms: "Edit symptoms",
    allow: "Allow",
    consentTitle: "Sharing your pre-summary",
    consentScope:
      "This doctor will see your symptoms summary and may consult your consultations and prescriptions records while drafting your care.",
    consentValidity: "This access lasts until you revoke it.",
    confirmTitle: "Doctor chosen",
    confirmBody: "Your pre-summary is now visible to this doctor only.",
    whatHappensNext: "What happens next",
    whatHappensNextItems:
      "The doctor reviews your pre-summary. If needed, they will contact you for a consultation. You can track the status from your intake page.",
    loading: "Finding verified doctors…",
    recordingChoice: "Recording your choice…",
    genericError: "Something went wrong. Please try again.",
    viewIntakeStatus: "View intake status",
    errorTitle: "We couldn't load the doctor list",
    errorBody: "Check your connection and try again.",
    retry: "Try again",
    breadcrumb: "Choose doctor",
  },

  // findCare.* surface - PHASE-8.1 T11 (#485): the authed Find Care page at
  // /patient/find (blueprint §5.3). Reuses the verified directory browse;
  // the continuation CTA deep-links back into the intake pick step when an
  // intake is in progress (the intake flow carries ?intake=<id>).
  findCare: {
    resumeTitle: "A consultation is in progress",
    resumeBody:
      "Your pre-summary is ready. Resume choosing the doctor who will review it.",
    bookCta: "Book consultation",
  },
};

export type Dictionary = typeof en;
export type AuthStrings = Dictionary["auth"];
export type StaffAuthStrings = Dictionary["staffAuth"];
export type ProfileStrings = Dictionary["profile"];
export type DoctorStrings = Dictionary["doctor"];

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
        subtitle: "स्टाफ साइन-इन - डॉक्टर, लैब, केमिस्ट",
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
        codeInvalid: "कोड ठीक 6 अंकों का होना चाहिए।",
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
        genericError:
          "कुछ गड़बड़ हुई, कृपया अपनी साख़ीयाँ जाँचें और फिर से कोशिश करें।",
        invalidOperatorCode: "अमान्य प्रमाणीकरण कोड। कृपया फिर से कोशिश करें।",
        getCode: "वेरिफिकेशन कोड पाएँ",
        codeLabel: "वेरिफिकेशन कोड",
        codeHint: "SMS से भेजा गया 6 अंकों का कोड",
        codeExpires: "कोड समाप्त होने में",
        resend: "कोड फिर से भेजें",
        backToEdit: "नंबर बदलें",
        resendIn: (s) => `${s}s में फिर से भेजें`,
        attemptsLeft: (n) => `${n} प्रयास शेष`,
        noAttempts: "कोई प्रयास नहीं बचा। नया कोड माँगें।",
        wrongCode: (n) => `गलत कोड। ${n} प्रयास शेष।`,
        shortCode: "पूरा 6 अंकों का कोड दर्ज करें।",
        lockout: (m) => `बहुत अधिक गलत प्रयास। ${m} मिनट के लिए लॉक किया गया।`,
        resendEarly: (s) => `कूलडाउन सक्रिय। ${s}s में फिर से भेजें।`,
        expiredOrUsed: "यह कोड समाप्त या उपयोग हो चुका है। नया कोड माँगें।",
        latestWins: "नया कोड भेजा गया। पुराना कोड अब मान्य नहीं है।",
        suspendedNotice: "यह खाता निलंबित है। सहायता के लिए संपर्क करें।",
        noAccount:
          "इस नंबर के लिए कोई डॉक्टर, लैब या केमिस्ट खाता नहीं मिला। शुरू करने के लिए अपनी प्रैक्टिस या व्यवसाय रजिस्टर करें।",
        networkError: "सर्वर से संपर्क नहीं हो सका। अपना कनेक्शन जाँचें।",
        smsFailed: "कोड भेजा नहीं जा सका। कुछ देर में फिर कोशिश करें।",
        demoOtp: (code) => `डेमो OTP: ${code}`,
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
        phoneConfirm: {
          title: "अपना फ़ोन सत्यापित करें",
          helper:
            "आपके नियंत्रण वाले फ़ोन से आवेदन जुड़ा रहे, इसके लिए इस नंबर पर 6 अंकों का कोड SMS से भेजा गया है। खत्म करने के लिए कोड दर्ज करें - आपकी जानकारी सहेजी हुई है।",
          confirmCode: "कोड की पुष्टि करें",
        },
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
          mobileRequired: "अपना मोबाइल नंबर दर्ज करें।",
          mobileInvalid: "सही 10 अंकों का भारतीय मोबाइल नंबर दर्ज करें।",
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
        submitting: "जमा हो रहा है...",
        traceWithId: (traceId) => `ट्रेस: ${traceId}`,
        errorsSubmitLocationRequired:
          "आपका स्थान निर्धारित नहीं हो सका। कृपया स्थान की अनुमति दें और फिर से प्रयास करें।",
        errorsSubmitUnexpected:
          "अप्रत्याशित त्रुटि हुई। कृपया फिर से प्रयास करें।",
      },
    },
    doctor: {
      welcome: (displayName) => `स्वागत है, ${displayName}`,
      doctorLabel: "डॉक्टर",
      doctorWithPhone: (phone) => `डॉक्टर (${phone})`,
      workspaceActive: "आपका डॉक्टर वर्कस्पेस सक्रिय है।",
      statusHeading: "स्थिति",
      profileActive:
        "आपकी प्रोफ़ाइल सक्रिय और सत्यापित है। आप परामर्श स्वीकार करना शुरू कर सकते हैं।",
      nextStepsHeading: "अगले कदम",
      nextSteps: [
        "- अपनी पेशेवर प्रोफ़ाइल पूरी करें (जल्द आ रही है)",
        "- मरीज़ निर्देशिका ब्राउज़ करें (Phase 6)",
        "- किसी मरीज़ के रिकॉर्ड से परामर्श शुरू करें",
      ],
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

    directory: {
      heading: {
        all: "अपने आसपास जाँची-परखी देखभाल खोजें",
        doctor: "अपने आसपास डॉक्टर खोजें",
        lab: "अपने आसपास लैब खोजें",
        chemist: "अपने आसपास केमिस्ट खोजें",
      },
      subtitle:
        "केवल सक्रिय और वैध प्रमाण वाले प्रोवाइडर ही सूचीबद्ध होते हैं, दूरी के हिसाब से।",
      searchLabel: "प्रोवाइडर खोजें",
      searchPlaceholder: "नाम या विशेषज्ञता से खोजें",
      searchCta: "खोजें",
      filtersLabel: "प्रोवाइडर प्रकार और विशेषज्ञता से छाँटें",
      typeAll: "सभी",
      typeDoctor: "डॉक्टर",
      typeLab: "लैब",
      typeChemist: "केमिस्ट",
      specialties: {
        generalPhysician: "जनरल फ़िज़िशियन",
        pediatrician: "बाल रोग विशेषज्ञ",
        gynecologist: "स्त्री रोग विशेषज्ञ",
        dentist: "दंत चिकित्सक",
      },
      verified: "सत्यापित",
      locationDaltonganj: "डालटनगंज",
      distanceKm: (km: string) => `${km} किमी`,
      resultsCount: (n: number) => `${n} प्रोवाइडर मिले`,
      loading: "प्रोवाइडर खोजे जा रहे हैं...",
      emptyTitle: "इस खोज के लिए कोई प्रोवाइडर नहीं मिला",
      emptyBody: "अपनी खोज को और व्यापक बनाएँ या आस-पास के इलाक़े देखें।",
      clearSearch: "खोज साफ़ करें",
      outsideAreaLabel: "आपके इलाक़े के बाहर के प्रोवाइडर दिखाए जा रहे हैं",
      outsideAreaBody:
        "आपके चुने गए फ़िल्टर से आपके इलाक़े में कुछ नहीं मिला, इसलिए नज़दीकी उपलब्ध प्रोवाइडर दिखाए गए हैं। आपके फ़िल्टर वही रखे गए हैं।",
      errorTitle: "डायरेक्टरी लोड नहीं हो सकी",
      errorBody: "अपना कनेक्शन जाँचें और फिर कोशिश करें।",
      retry: "फिर कोशिश करें",
    },

    providerProfile: {
      verifiedByCareSetu: "CareSetu द्वारा सत्यापित",
      verified: "सत्यापित",
      active: "सक्रिय",
      credentialsHeading: "प्रमाण",
      credentialsAndLicensesHeading: "प्रमाण और लाइसेंस",
      practiceDetailsHeading: "अभ्यास विवरण",
      detailsHeading: "विवरण",
      typeLabel: "प्रकार",
      specialtyLabel: "विशेषज्ञता",
      areaLabel: "सेवा क्षेत्र",
      expiresOn: (date: string) => `${date} तक वैध`,
      credentialTypes: {
        medical_registration: "मेडिकल पंजीकरण",
        qualification_certificate: "योग्यता प्रमाणपत्र",
        lab_license: "लैब लाइसेंस",
        accreditation: "मान्यता",
        drug_license: "दवा लाइसेंस",
        pharmacist_registration: "फार्मासिस्ट पंजीकरण",
      },
      typeDoctor: "डॉक्टर",
      typeLab: "प्रयोगशाला",
      typeChemist: "केमिस्ट",
      breadcrumbDirectory: "डायरेक्टरी",
      loadingProfile: "प्रोफ़ाइल लोड हो रही है",
      comingSoon: "जल्द आ रहा है",
      comingSoonBody: "बुकिंग और ऑर्डर एक भविष्य के चरण में उपलब्ध होंगे।",
      notFoundTitle: "प्रोवाइडर नहीं मिला",
      notFoundBody:
        "यह प्रोवाइडर डायरेक्टरी में सूचीबद्ध नहीं है या अब सक्रिय नहीं है। केवल सक्रिय और सत्यापित प्रोवाइडर ही यहाँ दिखाए जाते हैं।",
      notFoundCta: "डायरेक्टरी देखें",
      loadError: "यह प्रोवाइडर प्रोफ़ाइल लोड नहीं हो सकी।",
      retry: "फिर कोशिश करें",
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
      accessHistory: {
        heading: "रिकॉर्ड किसने देखा",
        loadError: "एक्सेस इतिहास लोड नहीं हो सका।",
        emptyTitle: "अभी कोई एक्सेस नहीं",
        emptyBody:
          "जब कोई डॉक्टर, लैब या केमिस्ट आपका रिकॉर्ड देखता है, तो वह यहाँ दिखेगा।",
        scopePrefix: "अनुमति का दायरा: ",
        deniedLabel: "अस्वीकृत",
        deniedReasonPrefix: "कारण: ",
      },
      placeholder: {
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

    intake: {
      breadcrumb: "विज़िट शुरू करें",
      title: "बताइए, आपको क्या परेशानी है",
      reassure: "न फ़ॉर्म, न टाइपिंग। इससे डॉक्टर आपको जल्दी समझ पाएँगे।",
      modeVoice: "बोलिए",
      modeVoiceSub: "हिंदी या अंग्रेज़ी में रिकॉर्ड करें",
      modeText: "लिखिए",
      modeTextSub: "अपने लक्षण लिखें",

      voice: {
        title: "अपने लक्षण रिकॉर्ड करें",
        breadcrumb: "वॉइस इंटेक",
        reassure: "सीधे-सीधे बोलिए - हिंदी या अंग्रेज़ी, दोनों चल जाएँगी।",
        statusIdle: "माइक दबाएँ और बताइए आपको क्या परेशानी है",
        statusRecording: "रिकॉर्ड हो रहा है… रोकने के लिए दबाएँ",
        statusPaused: "रुका हुआ - जारी रखने के लिए दबाएँ",
        statusPreview: "अपनी रिकॉर्डिंग सुनें",
        statusPending: "स्ट्रक्चरिंग… कृपया प्रतीक्षा करें",
        statusDone: "रिकॉर्डिंग ले ली गई",
        statusPoor: "साफ़ सुनाई नहीं दिया",
        pause: "विराम",
        resume: "फिर से शुरू",
        stop: "रोकें",
        play: "प्रीव्यू सुनें",
        stopPreview: "प्रीव्यू रोकें",
        recordAgain: "फिर से रिकॉर्ड करें",
        submit: "जमा करें",
        submitting: "स्ट्रक्चरिंग…",
        poorTitle: "हमें साफ़ सुनाई नहीं दिया",
        poorBody:
          "हम ठीक से सुन नहीं पाए। कृपया फिर से रिकॉर्ड करें या टाइप करें।",
        poorRetry: "फिर कोशिश करें",
        poorType: "टाइप करें",
        attemptsExhausted:
          "आपने 3 वॉइस सीमा पूरी कर ली है। कृपया अपने लक्षण टाइप करें।",
        doneBody: "ले ली गई। आपका प्री-सारांश तैयार हो रहा है।",
        next: "अपना प्री-सारांश देखें",
        uploadErrorTitle: "हम आपकी रिकॉर्डिंग नहीं भेज पाए",
        uploadErrorBody:
          "आपकी रिकॉर्डिंग सुरक्षित है। कनेक्शन जाँचकर फिर कोशिश करें।",
        micUnavailableTitle: "हम आपके माइक तक नहीं पहुँच पाए",
        micUnavailableBody: "माइक की अनुमति जाँचकर फिर कोशिश करें।",
      },
      text: {
        title: "अपने लक्षण लिखें",
        breadcrumb: "टेक्स्ट इंटेक",
        reassure:
          "अपने शब्दों में बताइए आपको क्या परेशानी है - हिंदी या अंग्रेज़ी।",
        placeholder: "जैसे- बुख़ार 2 दिन से, सूखी खाँसी, शरीर में दर्द...",
        langHint: "हिंदी और अंग्रेज़ी दोनों चलते हैं",
        emptyTitle: "आगे बढ़ने के लिए लक्षण लिखें",
        emptyBody: "कृपया सबमिट करने से पहले बताइए क्या परेशानी है।",
        voiceAttach: "वॉइस नोट जोड़ें",
        voiceAttachHint:
          "वैकल्पिक - अपने टेक्स्ट के साथ एक वॉइस रिकॉर्डिंग जोड़ें",
        voiceRecording: "रिकॉर्ड हो रहा है… रोकने के लिए दबाएँ",
        voiceStop: "रोकें",
        voicePreview: "वॉइस नोट जुड़ गया",
        voiceTooShortTitle: "आपका वॉइस नोट बहुत छोटा है",
        voiceTooShortBody:
          "नोट को 3 सेकंड से अधिक रखें, हटाएँ, या इसके बजाय अपने लक्षण टाइप करें।",
        voiceRemove: "हटाएँ",
        submit: "जमा करें",
        submitting: "स्ट्रक्चरिंग…",
        doneBody: "ले लिए गए। आपका प्री-सारांश तैयार हो रहा है।",
        next: "अपना प्री-सारांश देखें",
        uploadErrorTitle: "हम आपकी रिकॉर्डिंग नहीं भेज पाए",
        uploadErrorBody:
          "आपकी रिकॉर्डिंग सुरक्षित है। कनेक्शन जाँचकर फिर कोशिश करें।",
        micUnavailableTitle: "हम आपके माइक तक नहीं पहुँच पाए",
        micUnavailableBody: "माइक की अनुमति जाँचकर फिर कोशिश करें।",
      },

      // T18 (#362): प्री-सारांश रिव्यू पेज - ईमानदारी बैनर "AI ड्राफ़्ट -
      // डॉक्टर पुष्टि करेंगे" (ADR-0001), स्ट्रक्चरिंग विश्वास स्तर + संकेतक,
      // और कम-विश्वास ड्राफ़्ट के लिए शांत एम्बर (चेतावनी, लाल नहीं) डॉक्टर
      // जाँच अनिवार्य नोटिस। फ़ील्ड संपादन save-edits रूट से सहेजे जाते हैं
      // और सुधार के रूप में दिखते हैं। परामर्श बुकिंग की ओर जारी रखने का CTA।
      preSummary: {
        breadcrumb: "प्री-सारांश",
        title: "आपका प्री-सारांश",
        description: "हमने जो समझा उस पर एक नज़र। आप कुछ भी सुधार सकते हैं।",
        bannerLine1: "AI ड्राफ़्ट - आपका डॉक्टर इसकी पुष्टि करेगा",
        bannerLine2: "यह निदान नहीं है। आपका डॉक्टर इसकी पुष्टि करेगा।",
        lowBannerLine1: "AI को पूरा भरोसा नहीं है",
        lowBannerLine2: "इस्तेमाल से पहले डॉक्टर को यह जाँचना होगा।",
        lowVerifyLine:
          "यह प्री-सारांश किसी भी नुस्खे से पहले डॉक्टर की जाँच अनिवार्य करेगा।",
        confidence: "स्ट्रक्चरिंग विश्वास स्तर",
        lowTag: "कम विश्वास",
        groupTitle: "हमने जो समझा",
        editBtn: "इस सारांश को संपादित करें",
        confirmBtn: "पुष्टि करें और आगे बढ़ें",
        confirmBtnLow: "परामर्श जारी रखें",
        editNote: "आपके संपादन डॉक्टर को बेहतर समझने में मदद करते हैं।",
        cancelEdit: "रद्द करें",
        saveEdit: "संपादन सहेजें",
        savingEdit: "सहेजा जा रहा है…",
        correctionsTag: "सुधारा गया",
        doneClean: "ऐसे ही उपयोग करें",
        doneLow: "सारांश तैयार। डॉक्टर पुष्टि करेंगे।",
        bookTitle: "इस सारांश के साथ परामर्श बुक करें",
        bookSub: "एक डॉक्टर खोजें जो आपके प्री-सारांश की जाँच कर सके।",
        bookSubLow: "नुस्खे से पहले आपका डॉक्टर इस प्री-सारांश की जाँच करेगा।",
        loading: "आपका प्री-सारांश देखा जा रहा है…",
        emptyTitle: "आपका प्री-सारांश अभी तैयार नहीं है",
        emptyBody:
          "थोड़ी देर बाद फिर देखें - डॉक्टर आपके लक्षणों की समीक्षा करेंगे।",
        loadFailedTitle: "हम आपका प्री-सारांश लोड नहीं कर पाए",
        loadFailedBody: "कनेक्शन जाँचकर फिर कोशिश करें।",
        processingTitle: "आपका सारांश अभी तैयार हो रहा है",
        processingBody:
          "एआई आपका सारांश बना रहा है। इसमें आम तौर पर कुछ सेकंड लगते हैं।",
        processingFailedTitle: "आपका सारांश तैयार होने में बहुत समय लग गया",
        processingFailedBody:
          "हमें आपका प्री-सारांश नहीं मिला। कृपया वापस जाकर फिर से कोशिश करें।",
        degradedTitle: "आपका डॉक्टर इसे सीधे देखेंगे",
        degradedEvidenceTitle: "डॉक्टर क्या देखेंगे",
        degradedVoiceNote: "आपकी रिकॉर्डिंग डॉक्टर के साथ साझा कर दी गई है।",
        degradedBody:
          "इस विज़िट के लिए कोई AI प्री-सारांश नहीं है। आपका डॉक्टर आपके लक्षणों की सीधे समीक्षा करेगा।",
        degradedRefresh:
          "डॉक्टर की कार्रवाई होने पर यह पेज अपने आप अपडेट होगा।",
        degradedStatusLink: "इंटेक स्थिति पर वापस जाएँ",
        saveFailedTitle: "हम आपके संपादन सहेज नहीं पाए",
        saveFailedBody: "कनेक्शन जाँचकर फिर कोशिश करें।",
        fields: {
          chief_complaints: "मुख्य शिकायतें",
          symptoms: "लक्षण",
          duration: "अवधि",
        },
      },

      // T19 (#363): इंटेक स्थिति सूची - चार स्थितियाँ: सहेजा गया /
      // व्यवस्थित हो रहा है / जाँच के लिए तैयार / फिर से रिकॉर्ड करें,
      // बैकएंड मशीन स्थिति मानों पर 1:1 मैप (T02)। बैकएंड से ताज़ा
      // (get_intake / get_pre_summary)। तैयार प्री-सारांश पर जारी रखने का CTA।
      status: {
        breadcrumb: "स्थिति",
        title: "आपकी इंटेक स्थिति",
        description: "देखें आपकी जानकारी कहाँ तक पहुँची",
        refresh: "ताज़ा करें",
        refreshing: "जाँच हो रही है\u2026",
        captured: "सहेजा गया",
        capturedDesc: "आपके लक्षण दर्ज हो गए हैं।",
        structuring: "व्यवस्थित हो रहा है",
        structuringDesc:
          "AI आपकी जानकारी को डॉक्टर के लिए व्यवस्थित कर रहा है।",
        readyForReview: "जाँच के लिए तैयार",
        readyForReviewDesc: "आपकी जानकारी डॉक्टर द्वारा जाँच के लिए तैयार है।",
        rawReviewNote:
          "इस विज़िट के लिए कोई AI प्री-सारांश नहीं है। आपका डॉक्टर आपकी दी गई जानकारी की सीधे समीक्षा करेगा।",
        reRecord: "फिर से रिकॉर्ड करें",
        reRecordDesc:
          "हम आपकी रिकॉर्डिंग ठीक से समझ नहीं पाए। कृपया फिर से रिकॉर्ड करें या लक्षण टाइप करें।",
        failed: "कुछ गड़बड़ हो गई",
        failedDesc:
          "हम आपकी जानकारी प्रोसेस नहीं कर पाए। कृपया नई विज़िट शुरू करें।",
        continue: "परामर्श जारी रखें",
        reRecordAction: "फिर से रिकॉर्ड करें",
        typeInstead: "टाइप करें",
        loading: "आपकी इंटेक स्थिति लोड हो रही है\u2026",
        loadFailedTitle: "हम आपकी स्थिति लोड नहीं कर पाए",
        loadFailedBody: "कनेक्शन जाँचकर फिर कोशिश करें।",
      },
    },

    // doctorConsole.* सतह - PHASE-8.1 T12 (#450): डॉक्टर कंसोल लैंडिंग पेज।
    // दो सेक्शन: समीक्षा कतार (कम विश्वास पहले, पुराने पहले) और खुले केयर केस,
    // साथ ही शुल्क संपादक, आने वाले मरीज़/प्रोफ़ाइल, और लोड विफलता पर पुनः प्रयास।
    // सभी कॉपी द्विभाषी en/hi (REQ-006)।
    doctorConsole: {
      title: "डॉक्टर कंसोल",
      consoleDescription: "आपकी समीक्षा कतार और खुले मामले",
      queueHeading: "समीक्षा कतार",
      queueEmpty: "समीक्षा के लिए कोई प्री-सारांश नहीं",
      queueItemMeta: (id: number) => `इनटेक #${id}`,
      caseItemMeta: (id: number) => `केस #${id}`,
      verifyChip: "जाँचें",
      confidenceLabel: "विश्वास",
      waitingFor: (time: string) => `${time} से प्रतीक्षा`,
      reviewAction: "समीक्षा करें",
      casesHeading: "खुले मामले",
      casesEmpty: "कोई खुला केयर केस नहीं",
      casesIndexTitle: "मेरे मामले",
      casesIndexDescription: "आपके खुले केयर मामले",
      stagePreSummary: "प्री-सारांश",
      stagePrescriptionPending: "नुस्ख़ा लंबित",
      stageClosed: "बंद",
      openCaseAction: "खोलें",
      feeEditorHeading: "परामर्श शुल्क",
      feeEditorHelp:
        "वह शुल्क सेट करें जो मरीज़ आपको चुनने पर देखें। सेट न होने तक खाली रहेगा।",
      feeFieldLabel: "शुल्क (\u20B9)",
      feeFieldPlaceholder: "जैसे 400",
      saveFee: "शुल्क सहेजें",
      clearFee: "शुल्क हटाएँ",
      feeSaved: "शुल्क सहेजा गया।",
      feeSaveFailed: "शुल्क सहेजा नहीं जा सका।",
      patientsComingSoon: "मरीज़ - जल्द आ रहा है",
      profileComingSoon: "प्रोफ़ाइल - जल्द आ रहा है",
      comingSoonBody: "यह क्षेत्र बाद के अपडेट में खुलेगा।",
      loadFailed: "कंसोल लोड नहीं हो सका।",
      retry: "फिर से कोशिश करें",
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
      transcriptHeading: "मूल इंटेक",
      transcriptEmpty: "इस इंटेक के लिए कोई प्रतिलेख उपलब्ध नहीं है।",
      transcriptLoadFail: "इंटेक प्रतिलेख लोड नहीं हो सका।",
      audioPlayLabel: "रिकॉर्डिंग चलाएँ",
      audioLoadFail: "रिकॉर्डिंग लोड नहीं हो सकी।",
      loadFailed: "यह केस वर्कस्पेस लोड नहीं हो सका।",
      retry: "फिर कोशिश करें",
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
        "अभी कोई नुस्ख़ा मसौदा नहीं है। शुरू करने के लिए AI मसौदा माँगें।",
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
      approvalGateTitle: "समीक्षा करें और अनुमोदित करें",
      approvalGateHelp:
        "जारी करने से पहले पुष्टि करें कि आपने हर वस्तु मरीज़ के रिकॉर्ड के अनुसार जाँची है।",
      verificationDeclaration:
        "मैंने यह नुस्ख़ा जाँच लिया है (Maine check kar liya)",
      approveIssueAction: "अनुमोदित करें और जारी करें",
      approvingIssuance: "अनुमोदित हो रहा है",
      approveBlockedHelp:
        "नुस्ख़ा अनुमोदित और जारी करने के लिए सत्यापन घोषणा पर टिक करें।",
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
