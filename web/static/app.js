"use strict";

const $ = (sel) => document.querySelector(sel);
const api = {
  get: (url) => fetch(url).then((r) => r.json()),
  post: (url, body) =>
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
};

let current = null; // { subject, set, questions }

// ---------- 标签页切换 ----------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    $("#" + tab.dataset.tab).classList.add("active");
    if (tab.dataset.tab === "dashboard") loadDashboard();
  });
});

// ---------- 加载套题列表 ----------
async function loadSubjects() {
  const data = await api.get("/api/subjects");
  const sel = $("#subjectSelect");
  sel.innerHTML = "";
  (data.sets || []).forEach((s, i) => {
    const opt = document.createElement("option");
    opt.value = JSON.stringify({ subject: s.subject, set: s.set });
    opt.textContent = `${s.subject} · ${s.set}（${s.n_questions} 题${s.has_key ? "，含答案键" : "，无答案键"}）`;
    sel.appendChild(opt);
  });
  if (!data.sets || data.sets.length === 0) {
    sel.innerHTML = '<option value="">（暂无可刷题套题）</option>';
    $("#startBtn").disabled = true;
  }
}

// ---------- 开始答题 ----------
$("#startBtn").addEventListener("click", async () => {
  const raw = $("#subjectSelect").value;
  if (!raw) return;
  const { subject, set } = JSON.parse(raw);
  const data = await api.get(`/api/quiz?subject=${encodeURIComponent(subject)}&set=${encodeURIComponent(set)}`);
  current = { subject, set, questions: data.questions };
  $("#quizMeta").textContent = `共 ${data.questions.length} 题`;
  renderQuiz(data.questions);
});

function renderQuiz(questions) {
  const area = $("#quizArea");
  area.innerHTML = "";
  questions.forEach((q, idx) => {
    const card = document.createElement("div");
    card.className = "q-card";
    card.dataset.id = q.id;
    const optsHtml =
      q.options && q.options.length
        ? `<div class="options">${q.options
            .map(
              (o) =>
                `<label class="opt"><input type="radio" name="q-${q.id}" value="${o.label}" /> <b>${o.label}.</b> ${escapeHtml(o.text)}</label>`
            )
            .join("")}</div>`
        : `<textarea class="answer" data-id="${q.id}" placeholder="在此输入你的作答…"></textarea>`;
    card.innerHTML = `
      <div class="q-head">第 ${q.index} 题（${q.id}）<span class="q-tag">${q.type} · ${q.difficulty}</span></div>
      <div class="q-stem">${escapeHtml(q.stem)}</div>
      ${optsHtml}
      <div class="result-line" id="res-${q.id}"></div>`;
    area.appendChild(card);
  });
  const submit = document.createElement("button");
  submit.className = "btn primary";
  submit.textContent = "提交并判分";
  submit.addEventListener("click", submitAnswers);
  area.appendChild(submit);
}

function collectAnswers() {
  const ans = {};
  document.querySelectorAll(".q-card").forEach((card) => {
    const id = card.dataset.id;
    const radio = card.querySelector(`input[name="q-${id}"]:checked`);
    if (radio) {
      ans[id] = radio.value;
    } else {
      const ta = card.querySelector("textarea.answer");
      if (ta) ans[id] = ta.value;
    }
  });
  return ans;
}

async function submitAnswers() {
  if (!current) return;
  const answers = collectAnswers();
  const res = await api.post("/api/submit", {
    subject: current.subject,
    set: current.set,
    answers,
  });
  if (res.error) {
    alert(res.error);
    return;
  }
  renderResults(res.results);
  loadDashboard();
}

function renderResults(results) {
  results.forEach((r) => {
    const el = $("#res-" + r.id);
    if (!el) return;
    let verdict, cls;
    if (r.correct === true) { verdict = "✅ 正确"; cls = "ok"; }
    else if (r.correct === false) { verdict = "❌ 错误"; cls = "bad"; }
    else { verdict = "⏳ 待复核"; cls = "pending"; }
    let extra = "";
    if (r.type === "选择题" && r.correct === false) {
      extra = `（你的选项：${r.student || "—"}，正确答案：${r.key_answer}）`;
    }
    el.innerHTML = `<span class="${cls}">${verdict}</span> ${extra}
      <div class="note">错因类型：${r.error_type || "—"} ｜ ${escapeHtml(r.note || "")}</div>`;
  });
  const s = results[0] ? null : null;
  const sum = results.filter((r) => r.correct === true).length;
  const meta = $("#quizMeta");
  meta.textContent = `本次正确 ${sum}/${results.length} 题（结果已写回题库文档）`;
}

// ---------- 监控 ----------
async function loadDashboard() {
  const d = await api.get("/api/dashboard");
  const area = $("#dashArea");
  if (!d.total_attempts) {
    area.innerHTML = '<p class="hint">暂无数据，先去「做题」提交一次吧。</p>';
    return;
  }
  const o = d.overall;
  const acc = (o.accuracy * 100).toFixed(1);
  let html = `<div class="cards">
    <div class="card"><div class="k">练习次数</div><div class="v">${d.total_attempts}</div></div>
    <div class="card"><div class="k">累计正确率</div><div class="v">${acc}%</div></div>
    <div class="card"><div class="k">累计题量（正确/总）</div><div class="v">${o.correct}/${o.total}</div></div>
    <div class="card"><div class="k">待复核题次</div><div class="v">${d.pending_review}</div></div>
  </div>`;

  if (d.weak_questions.length) {
    html += `<div class="section-title">薄弱题目（错得最多的）</div><table class="table">
      <tr><th>套题</th><th>题号</th><th>错次</th></tr>
      ${d.weak_questions
        .map((w) => `<tr><td>${w.subject} · ${w.set}</td><td>${w.id}</td><td>${w.count}</td></tr>`)
        .join("")}
    </table>`;
  }

  if (d.per_set.length) {
    html += `<div class="section-title">各套题情况</div><table class="table">
      <tr><th>套题</th><th>次数</th><th>正确率</th><th>最近</th><th>主要薄弱题</th></tr>
      ${d.per_set
        .map(
          (p) =>
            `<tr><td>${p.subject} · ${p.set}</td><td>${p.attempts}</td><td>${(p.accuracy * 100).toFixed(1)}%</td><td>${p.latest_ts}</td><td>${
              p.weak.length ? p.weak.slice(0, 3).map((x) => `${x[0]}×${x[1]}`).join("，") : "—"
            }</td></tr>`
        )
        .join("")}
    </table>`;
  }

  if (d.recent.length) {
    html += `<div class="section-title">最近练习</div><table class="table">
      <tr><th>时间</th><th>套题</th><th>对/总</th><th>待复核</th><th>错题</th></tr>
      ${d.recent
        .map(
          (r) =>
            `<tr><td>${r.ts}</td><td>${r.subject} · ${r.set}</td><td>${r.correct}/${r.total}</td><td>${r.pending}</td><td>${
              r.wrong_ids.join("，") || "—"
            }</td></tr>`
        )
        .join("")}
    </table>`;
  }

  area.innerHTML = html;
}

$("#refreshBtn").addEventListener("click", loadDashboard);

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

loadSubjects();
