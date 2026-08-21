import { useEffect, useRef, useState } from 'react';
import { isBlockedFrame, statsFromVideo } from '../webcam/frameCheck';

// Watches the camera for the whole exam and reports when it stops showing the candidate.
//
// There are two entirely separate ways a camera stops being useful, and they need different
// detection. Missing either one leaves an obvious hole.
//
// 1. THE TRACK STOPS DELIVERING. The old version of this check listened only for a track's
//    `ended` event, which is why switching the camera off mid-exam went undetected: `ended`
//    fires only when the track is permanently finished - device unplugged, or permission
//    revoked. The ordinary ways of switching a camera off produce something else:
//      - the OS camera toggle, or another application (Teams, Zoom) grabbing the device, leave
//        the track LIVE but set `muted = true`, firing a `mute` event
//      - `enabled = false` fires NO event at all
//      - a track removed from the stream fires `removetrack` on the STREAM, not the track
//
// 2. THE TRACK IS FINE BUT THE LENS IS COVERED. A physical privacy flap, tape, or a sticker.
//    Nothing at the API level changes at all: the track stays live, unmuted and enabled, and
//    keeps delivering frames at full frame rate. They are simply blank. No browser API exposes
//    "the shutter is shut", so the only signal is the pixels themselves.
//
// Case 2 was already solved for the ENTRY gate - services/webcam/frameCheck.js, used by
// ExamCameraPermission - but it ran exactly once, before the exam. A candidate could pass the
// gate with the flap open and close it a minute later, and nothing looked again. This hook runs
// the same analysis on a timer for the life of the exam, which is what closes that.
//
// The pixel analysis is imported rather than reimplemented so the in-exam check and the entry
// gate cannot drift apart in what they consider "covered".

// How often to look. The trade-off is detection latency against wasted work. Combined with
// CONSECUTIVE_BLOCKED_CHECKS below, a covered lens is reported six to eight seconds after it is
// covered: three checks at this interval, plus up to one further tick, because the frame the
// analysis reads lags the camera by a frame or two through the capture pipeline (measured).
const CHECK_MS = 2000;

// A covered lens must look covered several checks running before it is reported. One blank frame
// is not evidence: a candidate leaning close, a hand passing the lens, or the sensor
// re-adjusting exposure after a light change all produce a moment of near-uniform image. Several
// seconds of a blank lens is not something that happens by accident.
//
// Erring toward patience is deliberate here in a way it would not be for a tab switch: a false
// positive accuses someone of covering a camera they did not cover, and the evidence a TA would
// review afterwards is a recording that looks normal.
const CONSECUTIVE_BLOCKED_CHECKS = 3;

// Analyse a downscaled copy of the frame. At native resolution a single frame costs 40-70ms of
// main-thread work, which every two seconds is enough to be felt next to the session recorder's
// encoding; at this width it is 10-14ms. Verified not to weaken detection - see statsFromVideo.
const ANALYSIS_WIDTH = 320;

function hasLiveVideo(stream) {
  return stream.getVideoTracks().some(
    (track) => track.readyState === 'live' && !track.muted && track.enabled,
  );
}

/**
 * @param {React.MutableRefObject<MediaStream|null>} streamRef the exam's camera/mic stream
 * @param {boolean} active only guard while the exam is actually running
 * @param {(reason: string) => void} onViolation shared violation reporter
 * @returns {{cameraOff: boolean}} whether the camera is currently not showing the candidate
 */
export default function useCameraGuard(streamRef, active, onViolation) {
  const [cameraOff, setCameraOff] = useState(false);

  // Fires once per off-transition, not once per check. Continuous-off must NOT re-report: the
  // candidate has been warned and asked to restore the camera, and re-reporting every two
  // seconds while they slide the flap back open would terminate them for the act of complying.
  // Cleared when the camera returns, so a SECOND switch-off is reported - which is what makes
  // the "one warning, then out" rule apply here.
  const firedRef = useRef(false);

  useEffect(() => {
    if (!active) return undefined;
    const stream = streamRef.current;
    if (!stream) return undefined;

    // No video track at all means there is nothing to guard. This is the dev escape hatch
    // (?devNoCamera=1 in useCameraStream) producing an audio-only stream; without this the guard
    // would report camera_off the instant the exam started.
    if (stream.getVideoTracks().length === 0) return undefined;

    let cancelled = false;
    let blockedStreak = 0;

    // One offscreen <video> for the whole exam rather than one per check: attaching a stream and
    // waiting for it to produce frames costs a few hundred milliseconds, which would make a
    // 2-second poll mostly setup.
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    video.play().catch(() => {
      // A muted MediaStream is normally allowed to autoplay. If it is not, statsFromVideo
      // returns null (videoWidth stays 0), which isBlockedFrame treats as "not a working
      // camera" - the safe reading, and the streak requirement keeps it from firing on a single
      // slow start.
    });

    function report(off) {
      setCameraOff(off);
      if (off && !firedRef.current) {
        firedRef.current = true;
        onViolation('camera_off');
      } else if (!off) {
        firedRef.current = false;
      }
    }

    function check() {
      if (cancelled) return;

      // Track-level first: it is definitive and free. No live track means no frames worth
      // analysing, so the pixel check would only produce a second opinion on the same fact.
      if (!hasLiveVideo(stream)) {
        blockedStreak = 0;
        report(true);
        return;
      }

      // Track is live, so the camera claims to be working. Now find out whether it can actually
      // see anything.
      const blocked = isBlockedFrame(statsFromVideo(video, ANALYSIS_WIDTH));
      if (blocked) {
        blockedStreak += 1;
        // Report only once the streak is met, but keep counting past it so the state stays
        // "off" until the lens is genuinely uncovered.
        if (blockedStreak >= CONSECUTIVE_BLOCKED_CHECKS) report(true);
      } else {
        blockedStreak = 0;
        report(false);
      }
    }

    const tracks = stream.getVideoTracks();
    // 'mute' matters for the OS camera toggle or another app taking the device, 'ended' for an
    // unplugged one, 'unmute' so recovery is noticed promptly rather than on the next poll.
    const events = ['mute', 'unmute', 'ended'];
    tracks.forEach((track) => {
      events.forEach((name) => track.addEventListener(name, check));
    });
    stream.addEventListener('removetrack', check);

    const interval = setInterval(check, CHECK_MS);
    // Not called immediately: the offscreen video needs a moment to produce its first frame, and
    // a check before then reads videoWidth 0 and looks blank. The first interval tick is soon
    // enough, and the streak requirement covers the rest.

    return () => {
      cancelled = true;
      clearInterval(interval);
      tracks.forEach((track) => {
        events.forEach((name) => track.removeEventListener(name, check));
      });
      stream.removeEventListener('removetrack', check);
      // Detach but do NOT stop the tracks - the stream belongs to the exam session and the
      // recorder is still using it.
      video.srcObject = null;
    };
  }, [active, streamRef, onViolation]);

  return { cameraOff };
}
