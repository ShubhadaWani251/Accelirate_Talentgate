import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import PaginationControls from '../../components/common/PaginationControls';
import QuestionFormModal from '../../features/questions/QuestionFormModal';
import { ListPageSkeleton, SkeletonTableRows } from '../../components/loading/Skeleton';
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
  // Page-level skeleton on first paint only; section/difficulty/search changes keep the chrome
  // and skeleton just the table rows.
  const [firstLoad, setFirstLoad] = useState(true);
  const [editing, setEditing] = useState(null); // question object, or 'new'

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
      setFirstLoad(false);
    }
  }

  useEffect(() => {
    refresh(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionKey, difficulty, status]);

  const selectedSection = sections.find((s) => s.section_key === sectionKey);

  if (firstLoad && loading) {
    return (
      <ListPageSkeleton
        titleWidth={240} actions={1} filters={3} rows={6} columns={8}
        label="Loading question bank…"
      />
    );
  }

  return (
    <div>
      <h3>Question Bank Management</h3>

      {/* Counts come from the API, not from the loaded page: the question list is paginated, so
          the browser only ever holds one page and could not total a section itself. Clicking a
          card filters the table to that section - the cards double as the section picker the
          sidebar provides, which is what makes them worth the vertical space. */}
      <div className="grid-4" style={{ marginBottom: 16 }}>
        {sections.map((sec) => (
          <button
            key={sec.section_id}
            type="button"
            className={`stat-card qb-stat-card ${sectionKey === sec.section_key ? 'active' : ''}`}
            onClick={() => setSectionKey(sec.section_key)}
            style={{ textAlign: 'left', cursor: 'pointer', border: 'none', width: '100%' }}
          >
            <div className="stat-lbl" style={{ fontWeight: 600 }}>{sec.section_name}</div>
            <div className="stat-num" style={{ fontSize: 26 }}>{sec.total_questions ?? '—'}</div>
            <div className="stat-lbl">Total questions</div>
            <div style={{ display: 'flex', gap: 10, marginTop: 6, fontSize: 11.5 }}>
              <span style={{ color: 'var(--brand-green, #1a7f37)' }}>
                Active: <b>{sec.active_questions ?? '—'}</b>
              </span>
              <span style={{ color: 'var(--muted)' }}>
                Inactive: <b>{sec.inactive_questions ?? '—'}</b>
              </span>
            </div>
          </button>
        ))}
      </div>
      

      {/* Was an inline `gridTemplateColumns: '220px 1fr'`, which had no responsive behaviour and
          (because grid items default to min-width:auto) let the wide questions table push the
          whole page sideways below ~900px. The class stacks the sidebar under tablet/mobile and
          gives the content column min-width:0 so its table scroller can shrink instead. */}
      <div className="qb-layout">
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
          <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            {/* Only offered with a section selected, so a new question always lands in the
                section being browsed. Under "All Sections" there's no section to add to - the
                form used to silently fall back to the first one in the list. */}
            {selectedSection ? (
              <button className="btn primary" onClick={() => setEditing('new')}>
                + Add Question to {selectedSection.section_name}
              </button>
            ) : (
              <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>
                Pick a section on the left to add a single question to it.
              </span>
            )}
            {/* Bulk upload is section-agnostic: each row is filed by its own Section column,
                so one sheet can carry questions for several sections at once. Its own page
                rather than a modal - the validation table it leads to is far too wide for one. */}
            <Link to="/admin/question-bank/upload" className="btn"
                 >
              Bulk Upload (Excel)
            </Link>
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
              placeholder="Search questions by keyword or ID…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && refresh(1)}
              style={{ flex: 1, minWidth: 200, padding: '9px 12px', borderRadius: 8, border: '1px solid var(--line-soft)' }}
            />
            <button className="btn" onClick={() => refresh(1)}>Search</button>
          </div>

          <div className="table-scroll" aria-busy={loading}>
            <table className="data-table">
              <thead>
                <tr>
                  {/* '#' is the question's position WITHIN its section (1..n), which is
                      what the bank is read by. The global question_code is still stored and
                      still searchable (see the search box) - it just isn't a column any more. */}
                  <th>#</th><th>Section</th><th>Question</th><th>Options</th>
                  <th>Correct Answer</th>
                  <th>Difficulty</th><th>Marks</th><th>Status</th><th></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <SkeletonTableRows rows={6} columns={9} />
                ) : questions.length === 0 ? (
                  <tr><td colSpan={9}>No questions found.</td></tr>
                ) : (
                  questions.map((q) => (
                    <tr key={q.question_id}>
                      <td>{q.section_number ?? '—'}</td>
                      <td>{q.section_name}</td>
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
    </div>
  );
}
