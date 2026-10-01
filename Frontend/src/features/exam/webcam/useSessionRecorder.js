import { useEffect, useRef } from 'react';
import { uploadRecordingChunk } from '../../../api/examApi';

// 30s, not the 10s this used to be. Nothing watches the feed live - the recording exists to be
// reviewed after the fact - so uploading six times a minute per candidate bought nothing and cost
// a request each time. Every upload holds a gunicorn worker thread for a synchronous Azure append
// and writes last_activity_at, and there are only ~4 request slots per instance, so this is the
// single biggest lever on exam-time load: three times fewer requests for the same footage.
//
// Not longer than 30s, for two reasons. A browser crash loses at most the current chunk, so this
// is also the worst-case gap in somebody's proctoring evidence. And the bitrate hints below are
// hints - a browser is free to ignore them - so the chunk has to stay under
// DATA_UPLOAD_MAX_MEMORY_SIZE (10MB) even if it does: 30s at an ignored ~2.5Mbps default is ~9MB
// and still lands, where 60s would be ~18MB and would be refused and silently dropped.
const CHUNK_MS = 30000;

// Proctoring footage has to show a face, a desk and whether someone else is in the room. It does
// not have to be broadcast quality, and the browser default (commonly ~2.5Mbps) is far above what
// that needs - it inflates upload time, worker hold time, bandwidth and stored bytes by the same
// multiple. These are hints rather than guarantees; where a browser honours them a 30s chunk is
// roughly 1.6MB instead of ~9MB.
const VIDEO_BITS_PER_SECOND = 400_000;
const AUDIO_BITS_PER_SECOND = 32_000;

function pickMimeType() {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = ['video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4'];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || '';
}

// Continuous audio+video proctoring recording, chunked (~10s) so it survives a mid-exam crash
// and never buffers the full 45-minute exam in browser memory. Reuses the stream captured
// during identity verification - no second permission prompt.
export default function useSessionRecorder(stream, active) {
  const recorderRef = useRef(null);

  useEffect(() => {
    if (!active || !stream) return undefined;

    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, {
      ...(mimeType ? { mimeType } : {}),
      videoBitsPerSecond: VIDEO_BITS_PER_SECOND,
      audioBitsPerSecond: AUDIO_BITS_PER_SECOND,
    });
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        uploadRecordingChunk(event.data).catch((err) => {
          // Still best-effort - a dropped chunk must not interrupt the candidate's exam, which
          // is why this does not surface anything to them. But it is no longer silent: this used
          // to swallow every failure, so a recording could arrive with gaps - or be missing
          // almost entirely - and nothing anywhere would say so. A 413 here specifically means
          // the chunk exceeded DATA_UPLOAD_MAX_MEMORY_SIZE, which is the failure the chunk
          // length above is chosen to stay clear of.
          console.warn(
            '[proctoring] recording chunk upload failed',
            { bytes: event.data.size, status: err?.response?.status },
          );
        });
      }
    };
    recorder.start(CHUNK_MS);
    recorderRef.current = recorder;

    return () => {
      if (recorder.state !== 'inactive') recorder.stop();
      recorderRef.current = null;
    };
  }, [stream, active]);

  function stop() {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  return { stop };
}
