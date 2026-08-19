import { useEffect, useRef } from 'react';

// Live camera preview + a snapshot-to-Blob capture button. Used twice on the identity-capture
// screen (government ID, then live face) sharing the same underlying stream.
export default function PhotoCapture({ stream, label, hint, onCapture, captured }) {
  const videoRef = useRef(null);

  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  function capture() {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (blob) onCapture(blob);
    }, 'image/jpeg', 0.9);
  }

  return (
    <div className="card">
      <div className="box-label">{label}</div>
      {hint && <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 8 }}>{hint}</div>}
      {captured ? (
        <div className="alert success">✔ {label} captured</div>
      ) : (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          style={{ width: '100%', borderRadius: 8, background: '#111', display: 'block' }}
        />
      )}
      <div className="btn-row" style={{ marginTop: 10 }}>
        <button type="button" className="btn primary" onClick={capture} disabled={captured}>
          {captured ? 'Captured' : `Capture ${label}`}
        </button>
      </div>
    </div>
  );
}
