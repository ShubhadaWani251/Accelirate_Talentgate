import { useEffect, useRef } from 'react';
import { uploadRecordingChunk } from '../../../api/examApi';

const CHUNK_MS = 10000;

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
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        uploadRecordingChunk(event.data).catch(() => {
          // Best-effort - a dropped chunk shouldn't interrupt the candidate's exam.
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
