import { useEffect, useRef } from 'react';

// Two different severities live here, deliberately:
//   - Right-click is only ever silently blocked, never a termination trigger - it's too easy to
//     trigger by accident (a stray trackpad gesture), and termination is irreversible.
//   - Devtools/view-source/Print-Screen ARE zero-tolerance termination triggers, same as
//     tab-switching - nobody hits Ctrl+Shift+I or Print Screen by accident.
//
// What is and isn't detectable for screenshots (important, and not fixable in code):
//   - Bare `PrtScn` IS detectable - but on Windows/Chrome it very often fires ONLY `keyup`, never
//     `keydown`, which is why both are listened for below. A keydown-only handler misses it and
//     the termination gets attributed to the focus loss instead (reported as a tab switch).
//   - `Win+Shift+S` (Windows snipping), macOS `Cmd+Shift+4`, the Snipping Tool app, phone
//     cameras, and screen-share capture are ALL undetectable by any web page - Win/Cmd-key combos
//     are consumed by the OS and never delivered to the browser. Those still terminate the
//     attempt, but via the focus-loss guard, so they surface as "left the exam window" rather
//     than as a screenshot. There is no web API that closes this gap.
function isDevToolsCombo(e) {
  const key = e.key?.toLowerCase();
  return key === 'f12' || (e.ctrlKey && e.shiftKey && ['i', 'j', 'c'].includes(key));
}
function isViewSourceCombo(e) {
  return e.ctrlKey && e.key?.toLowerCase() === 'u';
}
// Some browsers report the bare key, others only expose it via the physical code.
function isPrintScreen(e) {
  return e.key === 'PrintScreen' || e.code === 'PrintScreen'
    || e.key === 'Snapshot' || e.keyCode === 44;
}

// `rearmKey` re-arms the latch after a warning for a DIFFERENT (warnable) trigger has been
// acknowledged, so a candidate who was warned for switching tabs can still be caught pressing
// F12 afterwards. The triggers in this hook are themselves never warnable - see
// exam_session.WARNABLE_REASONS.
export default function useExamLockdown(active, onViolation, rearmKey = 0) {
  const firedRef = useRef(false);

  useEffect(() => {
    if (!active) return undefined;
    firedRef.current = false;

    function trigger(reason) {
      if (firedRef.current) return;
      firedRef.current = true;
      onViolation(reason);
    }
    function blockContextMenu(e) {
      e.preventDefault();
    }
    function handleKeydown(e) {
      if (isDevToolsCombo(e)) {
        e.preventDefault();
        trigger('devtools_attempt');
      } else if (isViewSourceCombo(e)) {
        e.preventDefault();
        trigger('view_source_attempt');
      } else if (isPrintScreen(e)) {
        trigger('screenshot_attempt');
      }
    }
    // Separate keyup listener specifically for Print Screen - see the note above: Chrome on
    // Windows routinely delivers no keydown for it at all, only keyup.
    function handleKeyup(e) {
      if (isPrintScreen(e)) trigger('screenshot_attempt');
    }
    function warnBeforeUnload(e) {
      e.preventDefault();
      e.returnValue = '';
    }

    document.addEventListener('contextmenu', blockContextMenu);
    document.addEventListener('keydown', handleKeydown);
    document.addEventListener('keyup', handleKeyup);
    window.addEventListener('beforeunload', warnBeforeUnload);
    return () => {
      document.removeEventListener('contextmenu', blockContextMenu);
      document.removeEventListener('keydown', handleKeydown);
      document.removeEventListener('keyup', handleKeyup);
      window.removeEventListener('beforeunload', warnBeforeUnload);
    };
  }, [active, onViolation, rearmKey]);
}
