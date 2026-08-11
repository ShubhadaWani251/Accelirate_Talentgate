import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import * as candidateApi from '../../api/candidateApi';
import ConfigureBatchStep from '../../features/batches/ConfigureBatchStep';
import UploadStep from '../../features/batches/UploadStep';
import ReviewStep from '../../features/batches/ReviewStep';
import InviteConfirmationStep from '../../features/batches/InviteConfirmationStep';
import CandidateFilters from '../../features/candidates/CandidateFilters';
import CandidateTable from '../../features/candidates/CandidateTable';
import EditCandidateModal from '../../features/candidates/EditCandidateModal';
import NotifyModal from '../../features/candidates/NotifyModal';
import ExportModal from '../../features/candidates/ExportModal';
import PaginationControls from '../../components/common/PaginationControls';
import { extractErrorMessage } from '../../utils/passwordSchema';

const STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green' };
const EMPTY_FILTERS = { name: '', email: '', aadhaar: '', result: '', score_min: '', score_max: '' };

export default function BatchDetail() {
  const { id } = useParams();
  const [batch, setBatch] = useState(null);
  const [finalizeSummary, setFinalizeSummary] = useState(null);
  const [loading, setLoading] = useState(true);

  // Once a batch is finalized, this page gives it the same browse/select/notify/edit
  // capability as All Candidates, just pre-scoped to this one batch_id (wireframe parity -
  // previously this branch was a bare 4-column stub with a hardcoded Result column).
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [candidates, setCandidates] = useState([]);
  const [page, setPage] = useState(1);
  const [pageMeta, setPageMeta] = useState({ count: 0, next: null, previous: null });
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [editingCandidate, setEditingCandidate] = useState(null);
  const [notifyOpen, setNotifyOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setBatch(await batchApi.getBatch(id));
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function refreshCandidates(f = filters, p = page) {
    setCandidatesLoading(true);
    try {
      const data = await candidateApi.listCandidates({ ...f, batch_id: id, page: p });
      setCandidates(data.results);
      setPageMeta({ count: data.count, next: data.next, previous: data.previous });
      setPage(p);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setCandidatesLoading(false);
    }
  }

  useEffect(() => {
    if (batch && batch.status !== 'draft') refreshCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch?.status, id]);

  async function handleSendInvites() {
    try {
      const res = await batchApi.sendInvites(batch.batch_id);
      toast.success(res.detail);
      refresh();
      refreshCandidates();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    }
  }

  function toggleRow(candidateId) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(candidateId) ? next.delete(candidateId) : next.add(candidateId);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((prev) => (prev.size === candidates.length ? new Set() : new Set(candidates.map((c) => c.candidate_id))));
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
        <>
          <div className="btn-row" style={{ margin: '16px 0' }}>
            <button className="btn primary" style={{ width: 'auto' }} onClick={handleSendInvites}>
              📧 Send Invite Link(s)
            </button>
          </div>

          <CandidateFilters
            filters={filters}
            onChange={setFilters}
            batches={[]}
            onApply={() => refreshCandidates(filters, 1)}
            onClear={() => { setFilters(EMPTY_FILTERS); refreshCandidates(EMPTY_FILTERS, 1); }}
            showBatchFilter={false}
          />

          <CandidateTable
            candidates={candidates}
            loading={candidatesLoading}
            selected={selected}
            onToggleRow={toggleRow}
            onToggleSelectAll={toggleSelectAll}
            onEdit={setEditingCandidate}
            onOpenNotify={() => setNotifyOpen(true)}
            onOpenExport={() => setExportOpen(true)}
          />

          <PaginationControls
            page={page}
            count={pageMeta.count}
            hasPrevious={Boolean(pageMeta.previous)}
            hasNext={Boolean(pageMeta.next)}
            onPrev={() => refreshCandidates(filters, page - 1)}
            onNext={() => refreshCandidates(filters, page + 1)}
          />

          {editingCandidate && (
            <EditCandidateModal
              candidate={editingCandidate}
              onClose={() => setEditingCandidate(null)}
              onSaved={() => { setEditingCandidate(null); refreshCandidates(); }}
            />
          )}
          {notifyOpen && (
            <NotifyModal
              candidateIds={Array.from(selected)}
              onClose={() => setNotifyOpen(false)}
              onSent={() => { setNotifyOpen(false); setSelected(new Set()); }}
            />
          )}
          {exportOpen && <ExportModal onClose={() => setExportOpen(false)} batchId={batch.batch_id} />}
        </>
      )}

      {finalizeSummary && <InviteConfirmationStep summary={finalizeSummary} />}
    </div>
  );
}
