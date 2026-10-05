/** Select-all semantics for the candidate tables, shared by All Candidates and Batch Details.
 *
 * Both lists are paginated and both keep one selection across pages - a bulk invite or
 * notification is routinely assembled from people who do not all fit on one page. Both used to
 * get this wrong in the same two ways, having each written it separately:
 *
 *   1. Select All REPLACED the whole selection with the current page's ids, so ticking it on
 *      page 2 silently discarded everything chosen on page 1.
 *   2. The header checkbox asked `selected.size === candidates.length` - the TOTAL number
 *      selected against THIS PAGE's row count. Ten people selected across two pages of ten
 *      therefore read as "all selected", so the next click cleared the lot.
 *
 * Select All is a per-page control: it adds this page's rows to the selection, or removes them
 * if they are all already in it, and never touches rows it is not showing.
 */

/** True when every row currently on screen is selected. The header checkbox's checked state. */
export function allSelectedOnPage(selected, pageCandidates) {
  return pageCandidates.length > 0
    && pageCandidates.every((c) => selected.has(c.candidate_id));
}

/** True when some but not all of this page's rows are selected - the indeterminate dash. */
export function someSelectedOnPage(selected, pageCandidates) {
  return !allSelectedOnPage(selected, pageCandidates)
    && pageCandidates.some((c) => selected.has(c.candidate_id));
}

/** Next selection after Select All: this page added, or removed if it was already all in.
 *
 * Returns a new Set rather than mutating, so it can be passed straight to a setState updater. */
export function togglePageSelection(selected, pageCandidates) {
  const next = new Set(selected);
  const removing = allSelectedOnPage(selected, pageCandidates);
  pageCandidates.forEach((c) => {
    if (removing) next.delete(c.candidate_id);
    else next.add(c.candidate_id);
  });
  return next;
}

/** How many selected candidates are NOT on the current page.
 *
 * Worth showing: with the selection now surviving pagination, the action buttons can read
 * "(12)" while twelve rows are plainly not on screen. Saying where the rest are is the
 * difference between that looking correct and looking broken. */
export function selectedOffPageCount(selected, pageCandidates) {
  const onPage = new Set(pageCandidates.map((c) => c.candidate_id));
  let count = 0;
  selected.forEach((id) => { if (!onPage.has(id)) count += 1; });
  return count;
}
