// The blank filter state, in its own module rather than alongside CandidateFilters so that file
// exports nothing but its component - a file mixing component and non-component exports loses
// Vite's Fast Refresh for the whole module (react-refresh/only-export-components).
//
// Every key maps 1:1 onto a backend query param. Empty strings rather than nulls because these
// feed controlled inputs directly.
//
// The per-section score keys (<section_key>_min / _max) are deliberately NOT listed. They used
// to be, as a fixed four - logical, quantitative, verbal, programming - which stopped being the
// truth once sections became something an admin adds and retires: the list could name a section
// that no longer exists and could never name one added later. CandidateFilters now renders a
// range per section it is given and writes those keys in on demand, and listCandidates only
// sends keys that hold a value, so an absent one is simply not filtered on.
//
// Clearing still works because both callers REPLACE the filter state with this object rather
// than merging into it, which drops any section keys that had been typed in.
export const EMPTY_CANDIDATE_FILTERS = {
  name: '', email: '', aadhaar: '', batch_id: '', result: '',
  score_min: '', score_max: '',
};
