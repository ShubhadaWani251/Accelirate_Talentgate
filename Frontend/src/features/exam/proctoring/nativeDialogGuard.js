// Opening a native OS dialog - so far, only the Aadhaar upload's <input type="file"> picker -
// makes the browser drop the Fullscreen API's fullscreen state on its own, the same real,
// unavoidable behavior RequireFullscreen's own comment already documents for camera/mic
// permission prompts. Without this, opening that file picker immediately triggered
// RequireFullscreen's "Return to Full-Screen" gate WHILE the native dialog was still open -
// unmounting the very <input> the OS dialog was about to hand a selected file back to, so the
// dialog completed with nowhere for its result to land (reported live: "choose file" shows the
// return-to-fullscreen screen immediately, and selecting a file afterwards does nothing).
//
// A module-level counter, not React state/context: it brackets one native dialog's lifetime
// (opened -> closed), which has nothing to do with any component's own render lifecycle - every
// consumer only ever needs the CURRENT value at the moment a fullscreenchange event fires, never
// a re-render of its own. A counter rather than a boolean purely as a defensive measure against
// begin() being called twice before the matching end() (shouldn't happen with one file input, but
// costs nothing to make safe).
let openDialogCount = 0;

export function isNativeDialogOpen() {
  return openDialogCount > 0;
}

/**
 * Call synchronously in the same event handler that triggers a native dialog (e.g. an
 * <input type="file">'s onClick, which runs before the OS dialog opens). Returns a matching
 * end() to call once the dialog resolves - selected, cancelled, or errored, whichever comes
 * first. Safe to call end() more than once.
 */
export function beginNativeDialog() {
  openDialogCount += 1;
  let ended = false;
  return function endNativeDialog() {
    if (ended) return;
    ended = true;
    openDialogCount = Math.max(0, openDialogCount - 1);
    if (openDialogCount === 0) {
      // fullscreenchange doesn't necessarily fire again just because the dialog closed (the
      // browser may have silently restored fullscreen, or may not have) - RequireFullscreen
      // listens for this to re-check the real state now that suppression has lifted.
      window.dispatchEvent(new Event('talentgate:nativedialogclose'));
    }
  };
}
