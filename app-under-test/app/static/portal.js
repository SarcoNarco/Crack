const roles = {
  teacher: { label: 'Teacher', token: 'token-teacher-fixed' },
  'student-a': { label: 'Student A', token: 'token-student-a-fixed' },
  'student-b': { label: 'Student B', token: 'token-student-b-fixed' },
}

const state = { role: 'teacher' }
const content = document.querySelector('#portal-content')
const status = document.querySelector('#portal-status')
const buttons = [...document.querySelectorAll('.role-button')]

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[character])
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${roles[state.role].token}`, ...(options.headers || {}) },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Portal request could not be completed.')
  }
  return response.json()
}

function setActiveRole() {
  buttons.forEach((button) => {
    const active = button.dataset.role === state.role
    button.classList.toggle('is-active', active)
    button.setAttribute('aria-pressed', String(active))
  })
}

function statePill(value) {
  return `<span class="state-pill state-${escapeHtml(value)}">${escapeHtml(value)}</span>`
}

function studentView(submission) {
  const published = submission.grade_status === 'published'
  const gradeSummary = published
    ? statePill('published')
    : '<span class="state-pill state-pending">Feedback pending</span>'
  const feedback = published
    ? `<section class="feedback" aria-labelledby="feedback-heading"><h3 id="feedback-heading">Teacher feedback</h3><p>${escapeHtml(submission.feedback)}</p></section>`
    : '<section class="feedback" aria-labelledby="feedback-heading"><h3 id="feedback-heading">Teacher feedback</h3><p>Feedback pending. Your teacher has not published feedback yet.</p></section>'
  return `
    <section class="welcome-card">
      <p class="eyebrow">${escapeHtml(roles[state.role].label)} workspace</p>
      <h2>Your submitted work</h2>
      <p>Only your own submission and grade information is shown in this normal portal view.</p>
    </section>
    <article class="submission-card">
      <div class="card-heading"><div><p class="eyebrow">${escapeHtml(submission.assignment_title)}</p><h2>${escapeHtml(submission.class_title)}</h2></div>${gradeSummary}</div>
      <section aria-labelledby="submission-heading"><h3 id="submission-heading">Submission</h3><p class="submission-body">${escapeHtml(submission.submission_body)}</p></section>
      ${feedback}
    </article>`
}

function teacherView(grades) {
  const context = grades[0]
  const rows = grades.map((grade) => `
    <article class="grade-card">
      <div class="card-heading"><div><p class="eyebrow">${escapeHtml(grade.assignment_title)}</p><h2>${escapeHtml(grade.student_name)}</h2></div>${statePill(grade.state)}</div>
      <p class="submission-body">${escapeHtml(grade.submission_body)}</p>
      <div class="feedback"><strong>Feedback</strong><p>${escapeHtml(grade.feedback)}</p></div>
      <div class="actions" aria-label="Grade actions for ${escapeHtml(grade.student_name)}">
        <button type="button" data-action="review" data-grade-id="${escapeHtml(grade.grade_id)}" ${grade.state !== 'draft' ? 'disabled' : ''}>Mark reviewed</button>
        <button type="button" class="secondary" data-action="publish" data-grade-id="${escapeHtml(grade.grade_id)}" ${grade.state === 'published' ? 'disabled' : ''}>Publish grade</button>
      </div>
    </article>`).join('')
  return `
    <section class="welcome-card">
      <p class="eyebrow">Teacher workspace</p>
      <h2>Grading queue</h2>
      <p>${context ? `${escapeHtml(context.class_title)} · ${escapeHtml(context.assignment_title)}` : 'No assignments need grading.'}</p>
    </section>
    <section class="grade-grid" aria-label="Student grading queue">${rows || '<p class="empty-state">No grades are assigned to this queue.</p>'}</section>`
}

async function loadPortal() {
  setActiveRole()
  content.replaceChildren()
  status.textContent = 'Loading class workspace…'
  status.className = 'portal-status'
  try {
    if (state.role === 'teacher') {
      const data = await request('/grades/mine')
      content.innerHTML = teacherView(data.grades)
    } else {
      const data = await request('/submissions/mine')
      const [submission] = data.submissions
      content.innerHTML = submission
        ? studentView(submission)
        : '<section class="empty-state"><h2>No submission found</h2><p>This synthetic student has no work for this assignment.</p></section>'
    }
    status.textContent = `${roles[state.role].label} workspace ready.`
    content.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', updateGrade))
  } catch (error) {
    status.textContent = 'Portal could not load this workspace.'
    status.className = 'portal-status is-error'
    content.innerHTML = `<section class="empty-state"><h2>Unable to load portal data</h2><p>${escapeHtml(error.message)}</p><button type="button" id="retry">Try again</button></section>`
    document.querySelector('#retry')?.addEventListener('click', loadPortal)
  }
}

async function updateGrade(event) {
  const button = event.currentTarget
  button.disabled = true
  status.textContent = 'Saving grade lifecycle change…'
  try {
    await request(`/grades/${encodeURIComponent(button.dataset.gradeId)}/${button.dataset.action}`, { method: 'POST' })
    await loadPortal()
  } catch (error) {
    status.textContent = error.message
    status.className = 'portal-status is-error'
    button.disabled = false
  }
}

buttons.forEach((button) => button.addEventListener('click', () => {
  state.role = button.dataset.role
  loadPortal()
}))

loadPortal()
