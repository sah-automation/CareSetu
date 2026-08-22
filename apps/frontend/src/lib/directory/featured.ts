// PHASE-2.6 T09 (#200) - MARKED INTEGRATION POINT (spec #191 decision 10,
// blueprint §3.1 section 5, gap G2). The public provider-directory API does
// not exist yet (Phase 3 EPIC-02 builds it); until then this resolves to an
// empty list so the homepage renders its honest "Directory launching soon
// in Daltonganj" empty state. No fake/static provider cards, ever.
//
// When the endpoint lands, replace the body of fetchFeaturedDoctors with the
// real call - the signature and shape stay. Only ACTIVATED providers may be
// returned (FEAT-004 Rule 1), so every card carries a truthful verified
// indicator by construction.

export interface FeaturedDoctor {
  id: number;
  name: string;
  specialty: string;
  consultType: string;
  area: string;
}

export async function fetchFeaturedDoctors(): Promise<FeaturedDoctor[]> {
  // No supply yet: verification backend is Phase 5, directory API Phase 3.
  return [];
}
