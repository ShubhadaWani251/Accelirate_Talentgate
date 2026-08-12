import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import PaginationControls from '../../components/common/PaginationControls';
import QuestionFormModal from '../../features/questions/QuestionFormModal';
import QuestionBulkUploadModal from '../../features/questions/QuestionBulkUploadModal';
import { extractErrorMessage } from '../../utils/passwordSchema';

const STATUS_PILL = { Active: 'green', Inactive: 'gray' };

export default function QuestionBank() {
  const [sections, setSections] = useState([]);
  const [sectionKey, setSectionKey] = useState('');
  const [difficulty, setDifficulty] = useState('');
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [questions, setQuestions] = useState([]);
  const [page, setPage] = useState(1);
  const [pageMeta, setPageMeta] = useState({ count: 0, next: null, previous: null });
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // question object, or 'new'
  const [bulkUploadOpen, setBulkUploadOpen] = useState(false);

  useEffect(() => {
    questionApi.getSections().then(setSections).catch((err) => toast.error(extractErrorMessage(err)));
  }, []);

  async function refresh(p = page) {
    setLoading(true);
    try {
      const data = await questionApi.listQuestions({
        section: sectionKey, difficulty, status, search, page: p,
      });
      setQuestions(data.results);
      setPageMeta({ count: data.count, next: data.next, previous: data.previous });
      setPage(p);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionKey, difficulty, status]);

  const selectedSection = sections.find((s) => s.section_key === sectionKey);

  return (
    <div>
      <h3>Question Bank Management</h3>
      <p style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: -6 }}>
        Click a section to browse questions; filter by difficulty or status, and edit questions,
        options, or active/inactive status.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 18 }}>
        <div className="card" style={{ padding: 12 }}>
          <div className="box-label">Sections</div>
          <div>
            <button
              className={`qb-side-item ${!sectionKey ? 'active' : ''}`}
              onClick={() => setSectionKey('')}
            >
              All Sections
            </button>
            {sections.map((s) => (
              <button
                key={s.section_id}
                className={`qb-side-item ${sectionKey === s.section_key ? 'active' : ''}`}
                onClick={() => setSectionKey(s.section_key)}
              >
                {s.section_name}
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
            <button className="btn primary" style={{ width: 'auto' }} onClick={() => setEditing('new')}>
              + Add Question
            </button>
            <button className="btn" onClick={() => setBulkUploadOpen(true)}>Bulk Upload (Excel)</button>
            <button className="btn" onClick={questionApi.downloadQuestionTemplate}>⬇ Download Sample Template</button>
          </div>

          <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
            <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)} style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid var(--line-soft)' }}>
              <option value="">Difficulty: All</option>
              <option value="Easy">Easy</option>
              <option value="Medium">Medium</option>
              <option value="Hard">Hard</option>
            </select>
            <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid var(--line-soft)' }}>
              <option value="">Status: All</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
            <input
              placeholder="🔍 Search questions by keyword or ID…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && refresh(1)}
              style={{ flex: 1, minWidth: 200, padding: '9px 12px', borderRadius: 8, border: '1px solid var(--line-soft)' }}
            />
            <button className="btn" onClick={() => refresh(1)}>Search</button>
          </div>

          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th><th>Question</th><th>Options</th><th>Correct Answer</th>
                  <th>Difficulty</th><th>Marks</th><th>Status</th><th></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={8}>Loading…</td></tr>
                ) : questions.length === 0 ? (
                  <tr><td colSpan={8}>No questions found.</td></tr>
                ) : (
                  questions.map((q) => (
                    <tr key={q.question_id}>
                      <td>{q.question_code}</td>
                      <td style={{ whiteSpace: 'normal', minWidth: 220 }}>{q.question_text}</td>
                      <td style={{ whiteSpace: 'normal' }}>
                        A: {q.option_a}<br />B: {q.option_b}
                        {q.option_c && <>, C: {q.option_c}</>}
                        {q.option_d && <>, D: {q.option_d}</>}
                      </td>
                      <td><b>Option {q.correct_option}</b></td>
                      <td>{q.difficulty_display}</td>
                      <td>{q.marks}</td>
                      <td><span className={`pill ${STATUS_PILL[q.status] || 'gray'}`}>{q.status_display}</span></td>
                      <td><button className="btn small" onClick={() => setEditing(q)}>Edit</button></td>
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
            onPrev={() => refresh(page - 1)}
            onNext={() => refresh(page + 1)}
          />
        </div>
      </div>

      {editing && (
        <QuestionFormModal
          question={editing === 'new' ? null : editing}
          sections={sections}
          defaultSectionId={selectedSection?.section_id}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh(page); }}
        />
      )}
      {bulkUploadOpen && (
        <QuestionBulkUploadModal
          onClose={() => setBulkUploadOpen(false)}
          onUploaded={() => refresh(1)}
        />
      )}
    </div>
  );
}
