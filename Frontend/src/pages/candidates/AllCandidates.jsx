import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import * as batchApi from '../../api/batchApi';
import CandidateFilters from '../../features/candidates/CandidateFilters';
import CandidateTable from '../../features/candidates/CandidateTable';
import EditCandidateModal from '../../features/candidates/EditCandidateModal';
import NotifyModal from '../../features/candidates/NotifyModal';
import ExportModal from '../../features/candidates/ExportModal';
import PaginationControls from '../../components/common/PaginationControls';
import { extractErrorMessage } from '../../utils/passwordSchema';

const EMPTY_FILTERS = { name: '', email: '', aadhaar: '', batch_id: '', result: '', score_min: '', score_max: '' };

export default function AllCandidates() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS, batch_id: searchParams.get('batch') || '' });
  const [candidates, setCandidates] = useState([]);
  const [page, setPage] = useState(1);
  const [pageMeta, setPageMeta] = useState({ count: 0, next: null, previous: null });
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(new Set());

  const [editingCandidate, setEditingCandidate] = useState(null);
  const [notifyOpen, setNotifyOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  useEffect(() => {
    // page_size covers every realistic batch count in one page - this dropdown needs all of
    // them, not just the first page (unlike the candidate table below, which is deliberately
    // paginated since candidate volume is the actual unbounded-growth concern).
    batchApi.listBatches('', { pageSize: 200 })
      .then((data) => setBatches(data.results))
      .catch((err) => toast.error(extractErrorMessage(err)));
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
      />

      <PaginationControls
        page={page}
        count={pageMeta.count}
        hasPrevious={Boolean(pageMeta.previous)}
        hasNext={Boolean(pageMeta.next)}
        onPrev={() => refresh(filters, page - 1)}
        onNext={() => refresh(filters, page + 1)}
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

      {exportOpen && <ExportModal onClose={() => setExportOpen(false)} />}
    </div>
  );
}
