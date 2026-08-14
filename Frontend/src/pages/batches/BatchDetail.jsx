import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import * as candidateApi from '../../api/candidateApi';
import ConfigureBatchStep from '../../features/batches/ConfigureBatchStep';
import DeactivateBatchModal from '../../features/batches/DeactivateBatchModal';
import UploadStep from '../../features/batches/UploadStep';
import ReviewStep from '../../features/batches/ReviewStep';
import InviteConfirmationStep from '../../features/batches/InviteConfirmationStep';
import CandidateFilters, { EMPTY_CANDIDATE_FILTERS } from '../../features/candidates/CandidateFilters';
import CandidateTable from '../../features/candidates/CandidateTable';
import EditCandidateModal from '../../features/candidates/EditCandidateModal';
import NotifyModal from '../../features/candidates/NotifyModal';
import CertificationModal from '../../features/candidates/CertificationModal';
import ExportModal from '../../features/candidates/ExportModal';
import PaginationControls from '../../components/common/PaginationControls';
import ConfirmModal from '../../components/common/ConfirmModal';
import { extractErrorMessage } from '../../utils/passwordSchema';

const STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green', cancelled: 'red' };

export default function BatchDetail() {
  const { id } = useParams();
  const [batch, setBatch] = useState(null);
  const [finalizeSummary, setFinalizeSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [deactivateOpen, setDeactivateOpen] = useState(false);
  const [inviteConfirmOpen, setInviteConfirmOpen] = useState(false);

  // Once a batch is finalized, this page gives it the same browse/select/notify/edit
  // capability as All Candidates, just pre-scoped to this one batch_id (wireframe parity -
  // previously this branch was a bare 4-column stub with a hardcoded Result column).
  const [filters, setFilters] = useState(EMPTY_CANDIDATE_FILTERS);
  const [candidates, setCandidates] = useState([]);
  const [page, setPage] = useState(1);
  const [pageMeta, setPageMeta] = useState({ count: 0, next: null, previous: null });
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [editingCandidate, setEditingCandidate] = useState(null);
  const [notifyOpen, setNotifyOpen] = useState(false);
  const [certificationOpen, setCertificationOpen] = useState(false);
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

  // Both requests fire together rather than chaining. The candidate list is keyed off the URL's
  // batch id, not anything in the batch response, so waiting for the batch to arrive first was
  // pure latency - a whole extra round-trip on a page that already costs two. A draft batch
  // renders the staging table instead, so its candidate results are simply unused.
  useEffect(() => {
    refresh();
    refreshCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Invites are sent to the checked rows only - never a blanket "everyone still pending",
  // which would sweep up anyone deliberately skipped during upload review.
  async function handleSendInvites() {
    setInviteConfirmOpen(false);
    try {
      const res = await batchApi.sendInvites(batch.batch_id, Array.from(selected));
      toast.success(res.detail);
      setSelected(new Set());
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

  const isDraft = batch.status === 'draft';
  const isCancelled = batch.status === 'cancelled';

  return (
    <div className="page-wide">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <h3>
          Batch Details — {batch.batch_name}{' '}
          <span className={`pill ${STATUS_PILL[batch.status] || 'gray'}`}>{batch.status_display}</span>
        </h3>
        {!isCancelled && (
          <button className="btn danger" onClick={() => setDeactivateOpen(true)}>Deactivate Batch</button>
        )}
      </div>

      {isCancelled && (
        <div className="alert error">
          This batch is deactivated. Its candidates and results remain available, but no further
          invites can be sent and its configuration is locked.
        </div>
      )}

      <div className="grid-4" style={{ marginBottom: 20 }}>
        <div className="stat-card"><div className="stat-num">{batch.total_candidates}</div><div className="stat-lbl">Candidates</div></div>
        <div className="stat-card"><div className="stat-num">{batch.pass_count}</div><div className="stat-lbl">Pass</div></div>
        <div className="stat-card"><div className="stat-num">{batch.fail_count}</div><div className="stat-lbl">Fail</div></div>
        <div className="stat-card"><div className="stat-num">{batch.borderline_count}</div><div className="stat-lbl">Borderline</div></div>
      </div>

      {/* Wireframe order for this screen is Filters, then Configure Batch, then the candidate
          table. A draft batch has no candidates to filter yet, so the filter box only appears
          once the batch is finalized. */}
      {!isDraft && (
        <CandidateFilters
          filters={filters}
          onChange={setFilters}
          batches={[]}
          onApply={() => refreshCandidates(filters, 1)}
          onClear={() => { setFilters(EMPTY_CANDIDATE_FILTERS); refreshCandidates(EMPTY_CANDIDATE_FILTERS, 1); }}
          showBatchFilter={false}
        />
      )}

      <ConfigureBatchStep
        existingBatch={batch}
        onCreated={(updated) => setBatch(updated)}
        readOnly={!isDraft}
        locked={isCancelled}
      />

      {isDraft && !finalizeSummary ? (
        <>
          <UploadStep batch={batch} onUploaded={refresh} />
          <ReviewStep batch={batch} onFinalized={setFinalizeSummary} />
        </>
      ) : isDraft ? null : (
        <>
          <CandidateTable
            candidates={candidates}
            loading={candidatesLoading}
            selected={selected}
            onToggleRow={toggleRow}
            onToggleSelectAll={toggleSelectAll}
            onEdit={setEditingCandidate}
            onOpenNotify={() => setNotifyOpen(true)}
            onOpenCertification={() => setCertificationOpen(true)}
            onOpenInvite={() => setInviteConfirmOpen(true)}
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
          {certificationOpen && (
            <CertificationModal
              candidateIds={Array.from(selected)}
              onClose={() => setCertificationOpen(false)}
              onSent={() => { setCertificationOpen(false); setSelected(new Set()); }}
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

      {finalizeSummary && (
        <InviteConfirmationStep
          summary={finalizeSummary}
          onBack={() => setFinalizeSummary(null)}
          onSent={() => { setFinalizeSummary(null); refresh(); refreshCandidates(); }}
        />
      )}

      {inviteConfirmOpen && (
        <ConfirmModal
          title="Send invite links?"
          message={`This emails the assessment link to the ${selected.size} selected candidate(s) on
                    "${batch.batch_name}". Anyone already invited is skipped. Invitation emails
                    cannot be recalled once sent.`}
          confirmLabel={`Send ${selected.size} Invite(s)`}
          onConfirm={handleSendInvites}
          onCancel={() => setInviteConfirmOpen(false)}
        />
      )}

      {deactivateOpen && (
        <DeactivateBatchModal
          batch={batch}
          onClose={() => setDeactivateOpen(false)}
          onDeactivated={(res) => {
            setDeactivateOpen(false);
            // The batch row survives deactivation, so stay here and show its new state
            // rather than navigating away.
            if (res.batch) setBatch(res.batch);
            else refresh();
          }}
        />
      )}
    </div>
  );
}
