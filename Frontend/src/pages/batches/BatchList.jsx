import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import PaginationControls from '../../components/common/PaginationControls';
import BatchStatusFilter from '../../components/common/BatchStatusFilter';
import { ListPageSkeleton, SkeletonTableRows } from '../../components/loading/Skeleton';
import { extractErrorMessage } from '../../utils/passwordSchema';
import DeleteDraftBatchModal from '../../features/batches/DeleteDraftBatchModal';

const STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green', cancelled: 'red' };
const EMPTY_MESSAGE = {
  active: 'No active batches found.',
  draft: 'No Draft batches found.',
  cancelled: 'No Cancelled batches found.',
  all: 'No batches yet.',
};

export default function BatchList() {
  const [batches, setBatches] = useState([]);
  const [page, setPage] = useState(1);
  const [pageMeta, setPageMeta] = useState({ count: 0, next: null, previous: null });
  const [loading, setLoading] = useState(true);
  // Page-level skeleton on first paint only; later searches/filters keep the chrome and show
  // skeleton rows in the table instead.
  const [firstLoad, setFirstLoad] = useState(true);
  const [search, setSearch] = useState('');
  // Same unified Batch Status filter as the Dashboard - "Active" (In Progress + Completed) by
  // default. Draft and Cancelled aren't hidden, just not shown until asked for: a Draft has no
  // candidates or results yet, and a Cancelled one isn't live work, so neither belongs in the
  // default working view.
  const [batchStatus, setBatchStatus] = useState('active');
  // The batch a delete is pending confirmation for - only ever a Draft row (see the button
  // below), so DeleteDraftBatchModal never has to guard against a non-draft target itself.
  const [deleteTarget, setDeleteTarget] = useState(null);

  async function refresh(q = search, p = page, status = batchStatus) {
    setLoading(true);
    try {
      const data = await batchApi.listBatches(q, { page: p, status });
      setBatches(data.results);
      setPageMeta({ count: data.count, next: data.next, previous: data.previous });
      setPage(p);
      setBatchStatus(status);
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

  if (firstLoad && loading) {
    return (
      <ListPageSkeleton
        titleWidth={120} actions={1} filters={2} rows={6} columns={8}
        label="Loading batches…"
      />
    );
  }

  return (
    <div>
      <h3>Batches</h3>
      <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <Link to="/batches/new" className="btn primary">
          + Upload New Candidates
        </Link>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                   flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
        <div className="search-bar" style={{ display: 'flex', gap: 8, flex: 1, minWidth: 260 }}>
          <input
            placeholder="Search by batch name or college…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && refresh(search, 1)}
            style={{ flex: 1, padding: '9px 12px', borderRadius: 8, border: '1px solid var(--line-soft)' }}
          />
          <button className="btn" onClick={() => refresh(search, 1)}>Search</button>
        </div>
        <BatchStatusFilter value={batchStatus} onChange={(status) => refresh(search, 1, status)} />
      </div>

      {batchStatus === 'draft' && (
        <div className="alert" style={{ marginBottom: 12 }}>
          These uploads were started but never completed — no batch has been created and no
          invites have been sent. Opening one resumes it at the step it was left on. A draft is
          kept until you either finish it or delete it yourself — nothing removes it
          automatically.
        </div>
      )}
      {batchStatus === 'cancelled' && (
        <div className="alert" style={{ marginBottom: 12 }}>
          These batches have been deactivated. Their candidates and results remain available for
          reference, but they can no longer send invites or accept new candidates.
        </div>
      )}

      <div className="table-scroll" aria-busy={loading}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Batch Name</th>
              <th>College</th>
              <th>TA Owner</th>
              <th>Candidates</th>
              <th>Status</th>
              <th>Pass</th>
              <th>Fail</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <SkeletonTableRows rows={6} columns={8} />
            ) : batches.length === 0 ? (
              <tr><td colSpan={8}>{EMPTY_MESSAGE[batchStatus] || 'No batches yet.'}</td></tr>
            ) : (
              batches.map((b) => (
                <tr key={b.batch_id}>
                  <td>{b.batch_name}</td>
                  {/* Optional at the batch level now - a mixed-college drive is normal, since
                      each candidate already carries their own college_name from the upload. */}
                  <td>{b.college_name || '—'}</td>
                  <td>{b.primary_ta_user_name}</td>
                  <td>{b.total_candidates}</td>
                  <td><span className={`pill ${STATUS_PILL[b.status] || 'gray'}`}>{b.status_display}</span></td>
                  <td>{b.pass_count}</td>
                  <td>{b.fail_count}</td>
                  {/* A draft reopens the upload wizard at its outstanding step; anything
                      finalized goes to its Batch Details page. */}
                  <td style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                    <Link
                      to={b.status === 'draft' ? `/batches/${b.batch_id}/continue` : `/batches/${b.batch_id}`}
                      className="link-text"
                    >
                      {b.status === 'draft' ? 'Continue' : 'View'}
                    </Link>
                    {b.status === 'draft' && (
                      <button
                        type="button"
                        className="link-text"
                        style={{ color: 'var(--brand-red)' }}
                        onClick={() => setDeleteTarget(b)}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <PaginationControls
        page={page}
        count={pageMeta.count}
        hasPrevious={Boolean(pageMeta.previous)}
        hasNext={Boolean(pageMeta.next)}
        onPrev={() => refresh(search, page - 1)}
        onNext={() => refresh(search, page + 1)}
        onPageChange={(p) => refresh(search, p)}
      />

      {deleteTarget && (
        <DeleteDraftBatchModal
          batch={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={() => {
            setDeleteTarget(null);
            // A page that's now short one row (possibly its only row) - re-fetch this same
            // page rather than trusting the count in local state to still be right.
            refresh(search, page);
          }}
        />
      )}
    </div>
  );
}
