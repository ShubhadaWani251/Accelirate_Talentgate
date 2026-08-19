// Detects a camera that is technically working but not actually seeing anything - a closed
// privacy shutter/flap, tape or a sticker over the lens, or a disabled sensor.
//
// This has to be done by inspecting pixels: getUserMedia SUCCEEDS with a closed flap. The device
// exists and permission is granted, so the browser hands back a live track and reports no error
// whatsoever - the frames are just blank. There is no API that exposes "the physical shutter is
// shut", so the only reliable signal is that the image carries no detail.

// A real scene - even a badly lit one - has meaningful pixel variation. A covered lens produces a
// near-uniform field. Standard deviation is the primary signal precisely because it catches BOTH a
// black shutter and a light-coloured sticker, where a brightness-only test would miss the latter.
const MAX_UNIFORM_STDDEV = 5;
// Backstop for a sensor returning essentially pure black.
const MAX_BLACK_MEAN = 10;
// Sampling every pixel of a 1080p frame is needless work; a coarse grid is just as conclusive.
const SAMPLE_STEP = 4;
// Cameras emit a few dark/garbage frames while exposure settles, so a single bad frame must not
// fail a candidate.
const SAMPLES = 3;
const SAMPLE_GAP_MS = 250;
// Give the sensor time to warm up before believing anything it produces.
const WARMUP_MS = 600;
const READY_TIMEOUT_MS = 5000;

function statsFromVideo(video) {
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height) return null;

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(video, 0, 0, width, height);

  const { data } = ctx.getImageData(0, 0, width, height);
  let sum = 0;
  let sumSq = 0;
  let count = 0;
  for (let i = 0; i < data.length; i += 4 * SAMPLE_STEP) {
    // Rec. 601 luma - closer to perceived brightness than a flat RGB average.
    const luma = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    sum += luma;
    sumSq += luma * luma;
    count += 1;
  }
  if (!count) return null;

  const mean = sum / count;
  const variance = Math.max(0, sumSq / count - mean * mean);
  return { mean, stddev: Math.sqrt(variance) };
}

function isBlockedFrame(stats) {
  if (!stats) return true; // no frame at all is not a working camera either
  return stats.stddev < MAX_UNIFORM_STDDEV || stats.mean < MAX_BLACK_MEAN;
}

/** Attaches the stream to an offscreen <video> and waits until it is actually producing frames. */
function playOffscreen(stream) {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;

    const timer = setTimeout(
      () => reject(new Error('Camera did not start producing video in time.')),
      READY_TIMEOUT_MS,
    );

    video.onloadeddata = () => {
      clearTimeout(timer);
      resolve(video);
    };
    video.play().catch(() => {
      // Autoplay of a muted stream is normally allowed; onloadeddata/timeout still governs.
    });
  });
}

/**
 * Returns {blocked, stats}. `blocked: true` means the camera is running but the lens is covered.
 * Pass an existing on-screen <video> element to check the live preview instead of an offscreen one.
 */
export async function checkCameraNotBlocked(stream, existingVideo = null) {
  const videoTrack = stream?.getVideoTracks?.()[0];
  // No video track at all is a separate condition, handled by the caller - not "covered".
  if (!videoTrack) return { blocked: false, stats: null, noVideoTrack: true };

  let video = existingVideo;
  let ownsVideo = false;
  if (!video) {
    video = await playOffscreen(stream);
    ownsVideo = true;
    await new Promise((r) => setTimeout(r, WARMUP_MS));
  }

  try {
    const samples = [];
    for (let i = 0; i < SAMPLES; i += 1) {
      samples.push(statsFromVideo(video));
      if (i < SAMPLES - 1) await new Promise((r) => setTimeout(r, SAMPLE_GAP_MS));
    }
    // Blocked only if EVERY sample looks blank - one settling frame can't fail a candidate.
    const blocked = samples.every(isBlockedFrame);
    const best = samples.reduce(
      (acc, s) => (s && (!acc || s.stddev > acc.stddev) ? s : acc),
      null,
    );
    return { blocked, stats: best, noVideoTrack: false };
  } finally {
    if (ownsVideo) {
      video.srcObject = null;
    }
  }
}

export { isBlockedFrame, statsFromVideo };
