import { useEffect, useState } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import * as candidateApi from '../../api/candidateApi';
import { selectRoleCode } from '../../features/auth/authSlice';
import ConfigureBatchStep from '../../features/batches/ConfigureBatchStep';
import DeactivateBatchModal from '../../features/batches/DeactivateBatchModal';
import CandidateFilters from '../../features/candidates/CandidateFilters';
import { EMPTY_CANDIDATE_FILTERS } from '../../features/candidates/candidateFilterDefaults';
import CandidateTable from '../../features/candidates/CandidateTable';
import EditCandidateModal from '../../features/candidates/EditCandidateModal';
import NotifyModal from '../../features/candidates/NotifyModal';
import CertificationModal from '../../features/candidates/CertificationModal';
import ExportModal from '../../features/candidates/ExportModal';
import PaginationControls from '../../components/common/PaginationControls';
import ServerErrorPage from '../../components/error/ServerErrorPage';
import { ButtonSpinner } from '../../components/loading/Spinner';
import NotFoundPage from '../../components/error/NotFoundPage';
import { isResourceMissing } from '../../utils/apiError';
import { Skeleton, SkeletonCard, SkeletonPage, SkeletonTable } from '../../components/loading/Skeleton';
import { extractErrorMessage } from '../../utils/passwordSchema';

const STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green', cancelled: 'red' };

export default function BatchDetail() {
  const { id } = useParams();
  const roleCode = useSelector(selectRoleCode);
  const isAdmin = roleCode === 'admin';
  const [batch, setBatch] = useState(null);
  const [loading, setLoading] = useState(true);
  // null | 'notfound' | 'server' - which error page (if any) replaces this page.
  const [loadError, setLoadError] = useState(null);
  const [deactivateOpen, setDeactivateOpen] = useState(false);

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
  const [inviteConfirmOpen, setInviteConfirmOpen] = useState(false);
  const [invitesSending, setInvitesSending] = useState(false);
  const [certificationOpen, setCertificationOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setBatch(await batchApi.getBatch(id));
      setLoadError(null);
    } catch (err) {
      toast.error(extractErrorMessage(err));
      // Otherwise batch stays null and the page shows "Loading…" permanently.
      setLoadError(isResourceMissing(err) ? 'notfound' : 'server');
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

  // Confirmed before sending: this emails real candidates a brand-new link, which invalidates
  // nothing but does mean the previous link is no longer the one they were told about.
  async function handleSendInvites() {
    setInvitesSending(true);
    try {
      const res = await candidateApi.resendInvitesBulk(Array.from(selected));
      toast.success(res.detail);
      setInviteConfirmOpen(false);
      setSelected(new Set());
      refreshCandidates();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setInvitesSending(false);
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

  if (loadError === 'notfound') return <NotFoundPage standalone={false} />;
  if (loadError) return <ServerErrorPage onRetry={refresh} />;

  if (loading || !batch) {
    return (
      <div className="page-wide">
        <SkeletonPage label="Loading batch…">
          <SkeletonCard lines={3} style={{ marginBottom: 20 }} />
          <div className="grid-4" style={{ marginBottom: 20 }}>
            {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} lines={1} />)}
          </div>
          <div className="card">
            <Skeleton width="30%" height={11} style={{ marginBottom: 14 }} />
            <SkeletonTable rows={6} columns={8} label="Loading candidates…" />
          </div>
        </SkeletonPage>
      </div>
    );
  }

  // A draft has no candidates, no results and no invites - every panel on this page would be
  // empty or zero. It's an unfinished upload, so it belongs in the wizard, resumed at whatever
  // step is still outstanding. This also covers arriving here by typing the URL directly.
  if (batch.status === 'draft') return <Navigate to={`/batches/${id}/continue`} replace />;

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
          This batch has been cancelled. New candidates cannot be processed or invited for this
          batch. Its existing candidates and results remain available for reference, but its
          configuration is locked.
        </div>
      )}

      <div className="grid-4" style={{ marginBottom: 20 }}>
        <div className="stat-card"><div className="stat-num">{batch.total_candidates}</div><div className="stat-lbl">Candidates</div></div>
        <div className="stat-card"><div className="stat-num">{batch.pass_count}</div><div className="stat-lbl">Pass</div></div>
        <div className="stat-card"><div className="stat-num">{batch.fail_count}</div><div className="stat-lbl">Fail</div></div>
        <div className="stat-card"><div className="stat-num">{batch.borderline_count}</div><div className="stat-lbl">Borderline</div></div>
      </div>

      {/* Wireframe order for this screen is Filters, then Configure Batch, then the candidate
          table. Only finalized batches reach this page - a draft is redirected to the upload
          wizard above - so all three are always shown. */}
      <CandidateFilters
        filters={filters}
        onChange={setFilters}
        batches={[]}
        onApply={() => refreshCandidates(filters, 1)}
        onClear={() => { setFilters(EMPTY_CANDIDATE_FILTERS); refreshCandidates(EMPTY_CANDIDATE_FILTERS, 1); }}
        showBatchFilter={false}
      />

      {/* Read-only: the configuration was locked the moment the batch left Draft, since
          changing question counts or cutoffs mid-flight would corrupt an exam in progress. */}
      <ConfigureBatchStep
        existingBatch={batch}
        onCreated={(updated) => setBatch(updated)}
        readOnly
        locked={isCancelled}
        canEditCutoffs={isAdmin}
      />

      <CandidateTable
        candidates={candidates}
        loading={candidatesLoading}
        selected={selected}
        onToggleRow={toggleRow}
        onToggleSelectAll={toggleSelectAll}
        onEdit={setEditingCandidate}
        onOpenInvite={() => setInviteConfirmOpen(true)}
        onOpenNotify={() => setNotifyOpen(true)}
        onOpenCertification={() => setCertificationOpen(true)}
        onOpenExport={() => setExportOpen(true)}
      />

      <PaginationControls
        page={page}
        count={pageMeta.count}
        hasPrevious={Boolean(pageMeta.previous)}
        hasNext={Boolean(pageMeta.next)}
        onPrev={() => refreshCandidates(filters, page - 1)}
        onNext={() => refreshCandidates(filters, page + 1)}
        onPageChange={(p) => refreshCandidates(filters, p)}
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
      {inviteConfirmOpen && (
        <div className="modal-overlay">
          <div className="modal-box">
            <h4>Send a new invite link?</h4>
            <p>
              {selected.size} selected candidate(s) will be emailed a <b>new</b> assessment
              link. Any link they were sent previously will no longer be the one they should
              use. Candidates who have already submitted or been terminated cannot retake the
              assessment.
            </p>
            <div className="btn-row">
              <button className="btn" type="button" onClick={() => setInviteConfirmOpen(false)}>
                Cancel
              </button>
              <button className="btn primary" type="button" disabled={invitesSending}
                      onClick={handleSendInvites}>
                <ButtonSpinner loading={invitesSending}>Send New Link</ButtonSpinner>
              </button>
            </div>
          </div>
        </div>
      )}

      {notifyOpen && (
        <NotifyModal
          candidateIds={Array.from(selected)}
          onClose={() => setNotifyOpen(false)}
          onSent={() => { setNotifyOpen(false); setSelected(new Set()); }}
        />
      )}
      {exportOpen && <ExportModal onClose={() => setExportOpen(false)} batchId={batch.batch_id} />}

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
