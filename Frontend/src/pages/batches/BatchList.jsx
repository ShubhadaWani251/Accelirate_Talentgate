import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import * as batchApi from '../../api/batchApi';

const STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green' };

export default function BatchList() {
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  function refresh(q = '') {
    setLoading(true);
    batchApi.listBatches(q).then((data) => {
      setBatches(data);
      setLoading(false);
    });
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div>
      <h3>Batches</h3>
      <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <Link to="/batches/new" className="btn primary" style={{ width: 'auto', textDecoration: 'none' }}>
          + Upload New Candidates
        </Link>
      </div>

      <div className="search-bar" style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          placeholder="Search by batch name or college…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && refresh(search)}
          style={{ flex: 1, padding: '9px 12px', borderRadius: 8, border: '1px solid var(--line-soft)' }}
        />
        <button className="btn" onClick={() => refresh(search)}>Search</button>
      </div>

      <div className="table-scroll">
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
              <tr><td colSpan={8}>Loading…</td></tr>
            ) : batches.length === 0 ? (
              <tr><td colSpan={8}>No batches yet.</td></tr>
            ) : (
              batches.map((b) => (
                <tr key={b.batch_id}>
                  <td>{b.batch_name}</td>
                  <td>{b.college_name}</td>
                  <td>{b.primary_ta_user_name}</td>
                  <td>{b.total_candidates}</td>
                  <td><span className={`pill ${STATUS_PILL[b.status] || 'gray'}`}>{b.status_display}</span></td>
                  <td>{b.pass_count}</td>
                  <td>{b.fail_count}</td>
                  <td><Link to={`/batches/${b.batch_id}`} className="link-text">View</Link></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
