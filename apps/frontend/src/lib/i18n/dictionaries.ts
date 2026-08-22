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
};

export type Dictionary = typeof en;
export type AuthStrings = Dictionary["auth"];

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
  },
};
