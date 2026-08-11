import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import ConfigureBatchStep from '../../features/batches/ConfigureBatchStep';
import UploadStep from '../../features/batches/UploadStep';
import ReviewStep from '../../features/batches/ReviewStep';
import InviteConfirmationStep from '../../features/batches/InviteConfirmationStep';
import { extractErrorMessage } from '../../utils/passwordSchema';

const STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green' };

export default function BatchDetail() {
  const { id } = useParams();
  const [batch, setBatch] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [finalizeSummary, setFinalizeSummary] = useState(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    const [b, c] = await Promise.all([batchApi.getBatch(id), batchApi.getStagingCandidates(id)]);
    setBatch(b);
    setCandidates(c);
    setLoading(false);
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function handleSendInvites() {
    try {
      const res = await batchApi.sendInvites(batch.batch_id);
      toast.success(res.detail);
      refresh();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    }
  }

  if (loading || !batch) return <div>Loading…</div>;

  return (
    <div style={{ maxWidth: 900 }}>
      <h3>
        Batch Details — {batch.batch_name}{' '}
        <span className={`pill ${STATUS_PILL[batch.status] || 'gray'}`}>{batch.status_display}</span>
      </h3>

      <div className="grid-4" style={{ marginBottom: 20 }}>
        <div className="stat-card"><div className="stat-num">{batch.total_candidates}</div><div className="stat-lbl">Candidates</div></div>
        <div className="stat-card"><div className="stat-num">{batch.pass_count}</div><div className="stat-lbl">Pass</div></div>
        <div className="stat-card"><div className="stat-num">{batch.fail_count}</div><div className="stat-lbl">Fail</div></div>
        <div className="stat-card"><div className="stat-num">{batch.borderline_count}</div><div className="stat-lbl">Borderline</div></div>
      </div>

      <ConfigureBatchStep existingBatch={batch} onCreated={(updated) => setBatch(updated)} />

      {batch.status === 'draft' ? (
        <>
          <UploadStep batch={batch} onUploaded={refresh} />
          <ReviewStep
            batch={batch}
            onFinalized={(summary) => {
              setFinalizeSummary(summary);
              refresh();
            }}
          />
        </>
      ) : (
        <div className="card">
          <div className="box-label">Candidates ({candidates.length})</div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>Name</th><th>Email</th><th>Status</th><th>Result</th></tr>
              </thead>
              <tbody>
                {candidates.map((c) => (
                  <tr key={c.candidate_id}>
                    <td>{c.full_name}</td>
                    <td>{c.email}</td>
                    <td>{c.validation_status_display}</td>
                    <td>—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="btn-row" style={{ marginTop: 14 }}>
            <button className="btn primary" style={{ width: 'auto' }} onClick={handleSendInvites}>
              📧 Send Invite Link(s)
            </button>
          </div>
        </div>
      )}

      {finalizeSummary && <InviteConfirmationStep summary={finalizeSummary} />}
    </div>
  );
}
