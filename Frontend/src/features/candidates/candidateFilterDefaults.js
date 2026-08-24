// The blank filter state, in its own module rather than alongside CandidateFilters so that file
// exports nothing but its component - a file mixing component and non-component exports loses
// Vite's Fast Refresh for the whole module (react-refresh/only-export-components).
//
// Every key maps 1:1 onto a backend query param, so a field absent here is a field the API will
// never be asked to filter on. Empty strings rather than nulls because these feed controlled
// inputs directly.
export const EMPTY_CANDIDATE_FILTERS = {
  name: '', email: '', aadhaar: '', batch_id: '', result: '',
  score_min: '', score_max: '',
  logical_min: '', logical_max: '',
  quantitative_min: '', quantitative_max: '',
  verbal_min: '', verbal_max: '',
  programming_min: '', programming_max: '',
};
