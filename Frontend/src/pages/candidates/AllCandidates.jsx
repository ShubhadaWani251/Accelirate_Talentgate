import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import * as batchApi from '../../api/batchApi';
import * as questionApi from '../../api/questionApi';
import CandidateFilters from '../../features/candidates/CandidateFilters';
import { EMPTY_CANDIDATE_FILTERS } from '../../features/candidates/candidateFilterDefaults';
import CandidateTable from '../../features/candidates/CandidateTable';
import EditCandidateModal from '../../features/candidates/EditCandidateModal';
import NotifyModal from '../../features/candidates/NotifyModal';
import CertificationModal from '../../features/candidates/CertificationModal';
import ExportModal from '../../features/candidates/ExportModal';
import PaginationControls from '../../components/common/PaginationControls';
import { ListPageSkeleton } from '../../components/loading/Skeleton';
import { ButtonSpinner } from '../../components/loading/Spinner';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { fromDatetimeLocalValue } from '../../utils/datetime';

const EMPTY_FILTERS = EMPTY_CANDIDATE_FILTERS;

export default function AllCandidates() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS, batch_id: searchParams.get('batch') || '' });
  const [candidates, setCandidates] = useState([]);
  const [page, setPage] = useState(1);
  const [pageMeta, setPageMeta] = useState({ count: 0, next: null, previous: null });
  const [batches, setBatches] = useState([]);
  // Every section that exists, for the table's score columns. All Candidates spans
  // batches that can run different sections, so the column set is the global one
  // rather than any single batch's.
  const [sections, setSections] = useState([]);
  const [loading, setLoading] = useState(true);
  // First paint only. Later loads (filter/page changes) keep the page chrome and show skeleton
  // rows inside the table instead - re-skeletoning the whole page for a filter change would
  // throw away context the user is still reading.
  const [firstLoad, setFirstLoad] = useState(true);
  const [selected, setSelected] = useState(new Set());

  const [editingCandidate, setEditingCandidate] = useState(null);
  const [notifyOpen, setNotifyOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [certificationOpen, setCertificationOpen] = useState(false);
  // Re-invite from here always carries its own explicit window rather than inheriting a
  // batch's: this page spans every batch, so the selection can legitimately contain candidates
  // from several of them at once and there is no single batch window to fall back to.
  const [inviteConfirmOpen, setInviteConfirmOpen] = useState(false);
  const [invitesSending, setInvitesSending] = useState(false);
  const [linkValidFrom, setLinkValidFrom] = useState('');
  const [linkValidUntil, setLinkValidUntil] = useState('');

  useEffect(() => {
    // page_size covers every realistic batch count in one page - this dropdown needs all of
    // them, not just the first page (unlike the candidate table below, which is deliberately
    // paginated since candidate volume is the actual unbounded-growth concern).
    //
    // status: 'all' - the batch list defaults to Active-only, but a Cancelled batch's
    // candidates stay fully visible here (only Draft staging rows are excluded, since a draft
    // has nothing to filter by yet). Without this override, a cancelled batch would vanish
    // from the dropdown while its candidates remained in the table with no way to filter to
    // just them.
    batchApi.listBatches('', { pageSize: 200, status: 'all' })
      .then((data) => setBatches(data.results))
      .catch((err) => toast.error(extractErrorMessage(err)));

    // Section list drives the table's score columns. A failure here is not worth a toast on top
    // of whatever else failed - the table simply renders without section columns rather than
    // blocking the page.
    questionApi.getSections().then(setSections).catch(() => {});
  }, []);

  async function refresh(f = filters, p = page) {
    setLoading(true);
    try {
      const data = await candidateApi.listCandidates({ ...f, page: p });
      setCandidates(data.results);
      setPageMeta({ count: data.count, next: data.next, previous: data.previous });
      setPage(p);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setLoading(false);
      setFirstLoad(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filterBatchName = useMemo(() => {
    if (!filters.batch_id) return null;
    return batches.find((b) => String(b.batch_id) === String(filters.batch_id))?.batch_name;
  }, [filters.batch_id, batches]);

  function clearBatchFilter() {
    const next = { ...filters, batch_id: '' };
    setFilters(next);
    setSearchParams({});
    refresh(next, 1);
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    setSearchParams({});
    refresh(EMPTY_FILTERS, 1);
  }

  // Emails every selected candidate a brand-new assessment link. Confirmed first because it
  // invalidates nothing but does mean the link they were originally told about is no longer
  // the one to use.
  async function handleSendInvites() {
    if (!linkValidFrom || !linkValidUntil) {
      toast.error('Both Link Valid From and Link Valid Until are required.');
      return;
    }
    if (linkValidUntil <= linkValidFrom) {
      toast.error('Link Valid Until must be after Link Valid From.');
      return;
    }
    setInvitesSending(true);
    try {
      const res = await candidateApi.resendInvitesBulk(Array.from(selected), {
        link_valid_from: fromDatetimeLocalValue(linkValidFrom),
        link_valid_until: fromDatetimeLocalValue(linkValidUntil),
      });
      toast.success(res.detail);
      setInviteConfirmOpen(false);
      setSelected(new Set());
      refresh();
    } catch (err) {
      toast.error(extractErrorMessage(err, ['link_valid_from', 'link_valid_until']));
    } finally {
      setInvitesSending(false);
    }
  }

  function toggleRow(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((prev) => (prev.size === candidates.length ? new Set() : new Set(candidates.map((c) => c.candidate_id))));
  }

  return (
    <div>
      {firstLoad && loading ? (
        <ListPageSkeleton
          titleWidth={190} actions={0} filters={3} rows={6} columns={12}
          label="Loading candidates…"
        />
      ) : (
      <>
      <h3>All Candidates</h3>

      {filterBatchName && (
        <div className="alert" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 14 }}>
          <span>Showing candidates from <b>{filterBatchName}</b> only</span>
          <button className="btn small" onClick={clearBatchFilter}>Clear filter — show all batches</button>
        </div>
      )}

      <CandidateFilters
        filters={filters}
        onChange={setFilters}
        batches={batches}
        onApply={() => refresh(filters, 1)}
        onClear={clearFilters}
        // The same list the table renders score columns from, so a filter exists for exactly
        // the columns on screen.
        sections={sections}
      />

      <CandidateTable
        candidates={candidates}
        loading={loading}
        selected={selected}
        onToggleRow={toggleRow}
        onToggleSelectAll={toggleSelectAll}
        onEdit={setEditingCandidate}
        onOpenNotify={() => setNotifyOpen(true)}
        onOpenExport={() => setExportOpen(true)}
        onOpenInvite={() => setInviteConfirmOpen(true)}
        sections={sections}
        onOpenCertification={() => setCertificationOpen(true)}
      />

      <PaginationControls
        page={page}
        count={pageMeta.count}
        hasPrevious={Boolean(pageMeta.previous)}
        hasNext={Boolean(pageMeta.next)}
        onPrev={() => refresh(filters, page - 1)}
        onNext={() => refresh(filters, page + 1)}
        onPageChange={(p) => refresh(filters, p)}
      />

      {editingCandidate && (
        <EditCandidateModal
          candidate={editingCandidate}
          onClose={() => setEditingCandidate(null)}
          onSaved={() => { setEditingCandidate(null); refresh(); }}
        />
      )}

      {notifyOpen && (
        <NotifyModal
          candidateIds={Array.from(selected)}
          onClose={() => setNotifyOpen(false)}
          onSent={() => { setNotifyOpen(false); setSelected(new Set()); }}
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
            {/* This window applies only to the invitations sent here, not to any batch's own
                dates - the selection can span multiple batches from this page. */}
            <div className="grid-2">
              <div className="field">
                <label htmlFor="all_link_valid_from">Link Valid From</label>
                <input id="all_link_valid_from" type="datetime-local" value={linkValidFrom}
                       onChange={(e) => setLinkValidFrom(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="all_link_valid_until">Link Valid Until</label>
                <input id="all_link_valid_until" type="datetime-local" value={linkValidUntil}
                       onChange={(e) => setLinkValidUntil(e.target.value)} />
              </div>
            </div>
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

      {exportOpen && <ExportModal onClose={() => setExportOpen(false)} />}
      </>
      )}
    </div>
  );
}
