import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { formatDateTime } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Matches the wireframe's per-candidate "History" modal: a Date/Time · Event · Batch table,
// or the "No history found" empty state when nothing has happened to this candidate yet.
// Read-only by design - on the upload screen the reviewer acts on what they read here by
// checking or unchecking the row, not by mutating the candidate from inside this modal.
export default function CandidateHistoryModal({ candidate, onClose }) {
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    candidateApi.getCandidateHistory(candidate.candidate_id)
      .then((data) => { if (!cancelled) setHistory(data); })
      .catch((err) => { if (!cancelled) toast.error(extractErrorMessage(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [candidate.candidate_id]);

  const events = history?.events || [];
  const name = history?.full_name || candidate.full_name;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
        <h4>History — {name}</h4>

        {loading ? (
          <p style={{ fontSize: 12.5, color: 'var(--muted)' }}>Loading…</p>
        ) : events.length === 0 ? (
          <div className="hist-empty"><div className="hist-icon">🗂</div>No history found</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Date/Time</th><th>Event</th><th>Batch</th></tr></thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={`${e.timestamp}-${i}`}>
                    <td>{formatDateTime(e.timestamp)}</td>
                    <td>{e.event}</td>
                    <td>{e.batch_name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 14 }}>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
