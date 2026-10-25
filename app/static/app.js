'use strict';
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const rub = n => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(Math.round(n)) + ' ₽';
const dt = s => new Date(s).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'medium' });
const ST = { DRAFT: ['Черновик', ''], SUBMITTED: ['Отправлена', 'blue'], VALIDATION: ['Проверка данных', 'blue'], ENRICHMENT: ['Запросы в источники', 'blue'],
  SCORING: ['Оценка риска', 'blue'], MANUAL_REVIEW: ['На рассмотрении андеррайтера', 'purple'], INFO_REQUESTED: ['Нужна информация', 'orange'],
  OFFER_READY: ['Предложение готово', 'green'], SIGNING: ['Подписание', 'green'], SIGNED: ['Подписан', 'green'], DISBURSED: ['Деньги выданы', 'green'],
  REJECTED: ['Отказ', 'red'], DECLINED: ['Вы отказались', ''], CANCELLED: ['Отозвана', ''] };
const STEPS = ['Заявка', 'Проверка данных', 'Источники', 'Оценка риска', 'Решение', 'Подписание', 'Выдача'];
const STEP_OF = { DRAFT: 0, SUBMITTED: 1, VALIDATION: 1, ENRICHMENT: 2, SCORING: 3, MANUAL_REVIEW: 4, INFO_REQUESTED: 1, OFFER_READY: 4, REJECTED: 4, SIGNING: 5, SIGNED: 6, DISBURSED: 7, DECLINED: 5, CANCELLED: 1 };
const TEST = [['7701000019', 'Пекарня Заря — чистая история → одобрение'], ['770100002083', 'ИП Смирнов — молодой бизнес → встречное предложение'],
  ['7701000033', 'ТехноЛогистик — крупная сумма → ручное рассмотрение'], ['7701000040', 'СтройРесурс — просрочки → отказ'],
  ['7701000058', 'Ромашка — ликвидация → отказ'], ['7701000065', 'Гелиос-Сервис — серая зона → ручное рассмотрение'], ['7701999993', 'Валидный ИНН, нет в реестре → запрос информации']];
const S = { token: localStorage.getItem('token'), user: JSON.parse(localStorage.getItem('user') || 'null'), products: [], filter: '', W: null, sig: '' };

async function api(p, o = {}) {
  const r = await fetch('/api' + p, { method: o.method || 'GET', headers: { 'Content-Type': 'application/json', ...(S.token ? { Authorization: 'Bearer ' + S.token } : {}) }, body: o.body ? JSON.stringify(o.body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401 && S.token) { logout(); throw new Error(j.detail || 'Сессия истекла'); }
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : (j.detail || []).map(d => d.msg).join('; ') || 'Ошибка запроса');
  return j;
}
function toast(m, err) { const t = $('#toast'); t.textContent = m; t.className = err ? 'err' : ''; t.style.display = 'block'; clearTimeout(t.h); t.h = setTimeout(() => t.style.display = 'none', 4500); }
function logout() { localStorage.clear(); S.token = S.user = null; location.hash = '#/login'; render(); }
const badge = s => `<span class="badge b-${ST[s][1]}">${ST[s][0]}</span>`;
const bank = () => S.user && S.user.role === 'underwriter';
const annuity = (a, r, n) => r ? a * (r / 1200) / (1 - Math.pow(1 + r / 1200, -n)) : a / n;
const kv = (l, v) => `<div><span>${l}</span><b>${v}</b></div>`;
const num = v => v === '' || v == null ? undefined : Number(v);

function header() {
  $('#top').innerHTML = `<div class="logo" data-act="home"><b>А</b>Кредитный кабинет МСБ</div><div class="sp"></div>` + (S.user ?
    `<span>${esc(S.user.name)}</span><span class="role ${bank() ? 'bank' : ''}">${bank() ? 'Банк' : 'Клиент'}</span><button class="sec" data-act="logout" style="padding:6px 14px">Выйти</button>` : '');
}

// ---------- роутер ----------
async function render() {
  header();
  const h = location.hash || '#/';
  if (!S.token) return loginView();
  try {
    if (h.startsWith('#/app/')) await detailView(h.slice(6));
    else if (h === '#/new' && !bank()) await wizardView();
    else if (h.startsWith('#/edit/') && !bank()) await wizardView(h.slice(7));
    else await listView();
  } catch (e) { toast(e.message, true); }
}
window.addEventListener('hashchange', () => { S.sig = ''; if (!location.hash.startsWith('#/new') && !location.hash.startsWith('#/edit')) S.W = null; render(); });

function loginView() {
  $('#app').innerHTML = `<div class="card login"><h1>Вход</h1><p class="sub">Демо-доступ, пароль у всех: <b>Demo#2026</b></p>
  <label>Логин</label><input id="lg" value="client1" autocomplete="username"><label>Пароль</label><input id="pw" type="password" value="Demo#2026" autocomplete="current-password">
  <p><button data-act="login" style="width:100%">Войти</button></p><div class="demo"><span style="color:var(--mut);font-size:13px">Быстрый вход:</span>
  ${['client1', 'client2', 'client3', 'underwriter'].map(u => `<button class="sec" data-act="fill" data-u="${u}">${u}</button>`).join('')}</div></div>`;
}

// ---------- список ----------
async function listView() {
  const q = bank() && S.filter ? '?status=' + S.filter : '';
  const [apps, stats] = await Promise.all([api('/applications' + q), bank() ? api('/bank/stats') : null]);
  S.sig = 'L' + JSON.stringify(apps.map(a => [a.id, a.version])) + JSON.stringify(stats);
  const total = stats ? Object.values(stats).reduce((a, b) => a + b, 0) : 0;
  const chips = stats ? `<div class="chips"><div class="chip ${!S.filter ? 'on' : ''}" data-act="filter" data-s="">Все<b>${total}</b></div>${Object.keys(ST).filter(s => stats[s]).map(s => `<div class="chip ${S.filter === s ? 'on' : ''}" data-act="filter" data-s="${s}">${ST[s][0]}<b>${stats[s]}</b></div>`).join('')}</div>` : '';
  $('#app').innerHTML = `<div class="between"><div><h1>${bank() ? 'Рабочее место банка' : 'Мои заявки на кредит'}</h1><p class="sub">${bank() ? 'Очередь заявок. Ручного решения ждут заявки в статусе «На рассмотрении андеррайтера».' : 'Выберите продукт, заполните заявку и отслеживайте решение прямо здесь.'}</p></div>
  ${bank() ? '' : '<button data-act="new">+ Новая заявка</button>'}</div>${chips}<div class="card">${apps.length ? `<table><tr><th>Номер</th><th>Продукт</th><th>Компания</th><th class="r">Сумма</th><th>Статус</th><th>Обновлена</th></tr>
  ${apps.map(a => `<tr class="click" data-act="open" data-id="${a.id}"><td><b>${a.id}</b></td><td>${esc(PN(a.product))}</td><td>${esc(a.company?.name || '—')}</td><td class="r">${a.amount ? rub(a.amount) : '—'}</td><td>${badge(a.status)}</td><td>${dt(a.updated_at)}</td></tr>`).join('')}</table>` : '<p class="sub">Заявок пока нет.</p>'}</div>`;
}
const PN = id => (S.products.find(p => p.id === id) || {}).name || id || 'Продукт не выбран';

// ---------- мастер заявки ----------
const WSTEPS = ['Продукт', 'Параметры', 'Компания', 'Финансы и документы', 'Проверка и отправка'];
async function wizardView(id) {
  if (!S.products.length) S.products = await api('/products');
  if (!S.W || (id && S.W.id !== id)) {
    if (id) { const a = await api('/applications/' + id); S.W = { id, step: 0, status: a.status, info: a.info_request, d: { product: a.product, amount: a.amount, term_months: a.term_months, purpose: a.purpose || '', company: a.company || {}, financials: a.financials || {}, documents: a.documents || [], consent: a.consent } }; }
    else S.W = { id: null, step: 0, d: { company: {}, financials: {}, documents: [], consent: false, purpose: '' } };
  }
  const W = S.W, d = W.d, p = S.products.find(x => x.id === d.product);
  const nav = `<div class="wiz">${WSTEPS.map((t, i) => `<a class="${i === W.step ? 'on' : ''}" data-act="goto" data-i="${i}">${i + 1}. ${t}</a>`).join('')}</div>`;
  let body = '';
  if (W.step === 0) body = `<h2>Какой кредит вам нужен?</h2><div class="prods">${S.products.map(x => `<div class="prod ${d.product === x.id ? 'sel' : ''}" data-act="pick" data-id="${x.id}"><b>${x.name}</b><p>${x.desc}</p><small>от ${rub(x.min_amount)} до ${rub(x.max_amount)}<br>на ${x.min_term}–${x.max_term} мес. · от ${x.base_rate}% годовых</small></div>`).join('')}</div>`;
  else if (!p) body = `<div class="note">Сначала выберите продукт на шаге 1.</div>`;
  else if (W.step === 1) body = `<h2>Параметры финансирования</h2><div class="row"><div><label>Сумма, ₽ (${rub(p.min_amount)} – ${rub(p.max_amount)})</label><input type="number" data-k="amount" data-n="1" value="${d.amount ?? ''}" min="${p.min_amount}" max="${p.max_amount}" step="10000"></div>
  <div><label>Срок, мес. (${p.min_term}–${p.max_term})</label><input type="number" data-k="term_months" data-n="1" value="${d.term_months ?? ''}" min="${p.min_term}" max="${p.max_term}"></div></div>
  <label>Цель финансирования</label><input data-k="purpose" value="${esc(d.purpose)}" maxlength="500" placeholder="Например: закупка сырья на сезон"><div id="calc" class="note"></div>`;
  else if (W.step === 2) { const c = d.company; body = `<h2>О компании</h2><div class="row"><div><label>ИНН (10 цифр — юрлицо, 12 — ИП)</label><input data-k="company.inn" value="${esc(c.inn || '')}" maxlength="12" inputmode="numeric"></div><div style="flex:0;align-self:flex-end"><button class="dark" data-act="lookup">Найти в реестре</button></div></div><div id="lk"></div>
  <div class="row"><div><label>Название компании / ИП</label><input data-k="company.name" value="${esc(c.name || '')}"></div><div><label>ОКВЭД</label><input data-k="company.okved" value="${esc(c.okved || '')}"></div></div>
  <div class="row"><div><label>ФИО представителя</label><input data-k="company.contact_name" value="${esc(c.contact_name || '')}"></div><div><label>Должность / роль</label><select data-k="company.contact_role">${['', 'Собственник', 'Генеральный директор', 'Финансовый директор / бухгалтер', 'Сотрудник по финансированию', 'Уполномоченный сотрудник'].map(r => `<option ${c.contact_role === r ? 'selected' : ''} value="${r}">${r || 'Выберите…'}</option>`).join('')}</select></div></div>
  <details><summary>Тестовые ИНН (синтетические данные симулятора ЕГРЮЛ/БКИ)</summary><table>${TEST.map(t => `<tr class="click" data-act="fillinn" data-v="${t[0]}"><td><b>${t[0]}</b></td><td>${t[1]}</td></tr>`).join('')}</table></details>`; }
  else if (W.step === 3) { const f = d.financials; body = `<h2>Финансовые показатели</h2><div class="row"><div><label>Выручка за 12 мес., ₽</label><input type="number" data-k="financials.revenue_year" data-n="1" value="${f.revenue_year ?? ''}"></div><div><label>Чистая прибыль за 12 мес., ₽</label><input type="number" data-k="financials.profit_year" data-n="1" value="${f.profit_year ?? ''}"></div><div><label>Платежи по действующим кредитам, ₽/мес.</label><input type="number" data-k="financials.monthly_obligations" data-n="1" value="${f.monthly_obligations ?? ''}"></div></div>
  <h2 style="margin-top:22px">Документы</h2>${d.amount > 1500000 ? '<div class="note">Для суммы свыше 1 500 000 ₽ нужна бухгалтерская отчётность.</div>' : ''}<div class="row"><div><label>Тип</label><select id="dk"><option value="financial_statements">Бухгалтерская отчётность</option><option value="egrul_extract">Выписка ЕГРЮЛ/ЕГРИП</option><option value="other">Другое</option></select></div><div><label>Файл (имитация загрузки: сохраняется только имя)</label><input type="file" id="df"></div></div>
  <ul class="l">${d.documents.map((x, i) => `<li>${esc(x.name)} <small>(${esc(x.kind)})</small> <a data-act="rmdoc" data-i="${i}">удалить</a></li>`).join('')}</ul>`; }
  else body = `<h2>Проверьте и отправьте</h2><div class="kv">${kv('Продукт', esc(p.name))}${kv('Сумма', rub(d.amount || 0))}${kv('Срок', (d.term_months || '—') + ' мес.')}${kv('Компания', esc(d.company.name || '—'))}${kv('ИНН', esc(d.company.inn || '—'))}${kv('Представитель', esc(d.company.contact_name || '—'))}${kv('Выручка', d.financials.revenue_year != null ? rub(d.financials.revenue_year) : '—')}${kv('Документов', d.documents.length)}</div>
  <label class="chk"><input type="checkbox" data-k="consent" data-b="1" ${d.consent ? 'checked' : ''}>Согласен на обработку данных компании и запрос сведений в БКИ и государственных реестрах (в демо — симуляторы)</label>`;
  const info = W.info ? `<div class="note err"><b>Банку нужна дополнительная информация:</b><ul class="l">${W.info.items.map(i => `<li>${esc(i)}</li>`).join('')}</ul>Исправьте данные и отправьте заявку повторно.</div>` : '';
  $('#app').innerHTML = `<p><a data-act="home">← К заявкам</a></p><h1>${W.status === 'INFO_REQUESTED' ? 'Дополнение заявки ' + W.id : 'Новая заявка'}</h1>${info}${nav}<div class="card">${body}</div>
  <div class="between"><button class="sec" data-act="prev" ${W.step ? '' : 'disabled'}>Назад</button><span><button class="sec" data-act="save">Сохранить черновик</button> ${W.step < 4 ? '<button data-act="next">Далее</button>' : `<button class="ok" data-act="send">${W.status === 'INFO_REQUESTED' ? 'Отправить повторно' : 'Отправить в банк'}</button>`}</span></div>`;
  calc();
}
function setPath(k, v) { const parts = k.split('.'); let o = S.W.d; parts.slice(0, -1).forEach(x => o = o[x] = o[x] || {}); o[parts.at(-1)] = v; }
function calc() {
  const el = $('#calc'), d = S.W && S.W.d, p = S.products.find(x => x.id === (d || {}).product);
  if (!el || !p) return;
  if (!d.amount || !d.term_months) { el.textContent = 'Укажите сумму и срок — покажем ориентировочный платёж.'; return; }
  el.innerHTML = `Ориентировочный платёж по базовой ставке ${p.base_rate}%: <b>${rub(annuity(d.amount, p.base_rate, d.term_months))}</b> в месяц. Итоговую ставку определит банк по результатам оценки (+0…7 п.п.).`;
}
async function saveDraft() {
  const d = S.W.d, b = { product: d.product, amount: d.amount, term_months: d.term_months, purpose: d.purpose, company: d.company, financials: d.financials, documents: d.documents, consent: d.consent };
  if (S.W.id) await api('/applications/' + S.W.id, { method: 'PUT', body: b });
  else { const a = await api('/applications', { method: 'POST', body: b }); S.W.id = a.id; }
}

// ---------- карточка заявки ----------
function schedule(o) {
  let bal = o.amount, rows = '';
  for (let i = 1; i <= o.term_months; i++) { const int = bal * o.rate / 1200, pr = o.payment - int; bal = Math.max(0, bal - pr); rows += `<tr><td>${i}</td><td class="r">${rub(o.payment)}</td><td class="r">${rub(int)}</td><td class="r">${rub(pr)}</td><td class="r">${rub(bal)}</td></tr>`; }
  return `<details><summary>График платежей (аннуитет)</summary><table><tr><th>№</th><th class="r">Платёж</th><th class="r">Проценты</th><th class="r">Основной долг</th><th class="r">Остаток</th></tr>${rows}</table></details>`;
}
function offerCard(a) {
  const o = a.offer; if (!o) return '';
  return `<div class="offer"><div class="between"><h2 style="margin:0">${o.kind === 'COUNTER' ? 'Встречное предложение банка' : 'Банк одобрил заявку'}</h2><span>действует до ${o.valid_until}</span></div>
  <div class="kv" style="margin-top:14px"><div><span>Сумма</span><b class="big">${rub(o.amount)}</b></div>${kv('Срок', o.term_months + ' мес.')}${kv('Ставка', o.rate + '% годовых')}${kv('Платёж в месяц', rub(o.payment))}${kv('Переплата', rub(o.overpayment))}</div></div>`;
}
function actionPanel(a) {
  const s = a.status, dec = a.decision;
  if (['SUBMITTED', 'VALIDATION', 'ENRICHMENT', 'SCORING'].includes(s)) return `<div class="card"><span class="spin"></span><b>Банк обрабатывает заявку…</b><p class="sub" style="margin:6px 0 0">Статус обновляется автоматически. Текущий этап: ${ST[s][0].toLowerCase()}.</p></div>`;
  if (s === 'MANUAL_REVIEW') return bank() ? decisionForm(a) : `<div class="card"><b>Заявку рассматривает кредитный специалист</b><p class="sub" style="margin:6px 0 0">Автоматическая проверка пройдена, нужен взгляд эксперта. Ничего делать не нужно — решение появится здесь.</p></div>`;
  if (s === 'INFO_REQUESTED') return `<div class="card"><div class="note err"><b>Нужна дополнительная информация</b><ul class="l">${(a.info_request?.items || []).map(i => `<li>${esc(i)}</li>`).join('')}</ul></div>${bank() ? '' : `<button data-act="edit" data-id="${a.id}">Дополнить заявку</button> <button class="sec" data-act="cancel" data-id="${a.id}">Отозвать заявку</button>`}</div>`;
  if (s === 'OFFER_READY') return offerCard(a) + `<div class="card">${dec ? `<p style="margin-top:0">${(dec.reasons || []).map(esc).join('; ')}</p>` : ''}${a.offer ? schedule(a.offer) : ''}${bank() ? '<p class="sub">Ожидается решение клиента.</p>' : `<p><button class="ok" data-act="accept" data-id="${a.id}">Принять предложение</button> <button class="sec" data-act="decline" data-id="${a.id}">Отказаться</button></p>`}</div>`;
  if (s === 'SIGNING') return offerCard(a) + `<div class="card"><h2>Подписание договора</h2><p>Кредитный договор № ${a.id}/КД на ${rub(a.offer.amount)}, ${a.offer.term_months} мес., ${a.offer.rate}% годовых. Подписание смоделировано без реальной электронной подписи.</p>${bank() ? '' : `<label class="chk"><input type="checkbox" id="sg">Я ознакомился с условиями и подписываю договор (имитация ЭП)</label><button class="ok" data-act="sign" data-id="${a.id}">Подписать договор</button>`}</div>`;
  if (['SIGNED', 'DISBURSED'].includes(s)) return offerCard(a) + `<div class="note ok"><b>Договор подписан, ${rub(a.offer.amount)} зачислены на расчётный счёт</b> (симуляция выдачи).</div><div class="card">${schedule(a.offer)}</div>`;
  if (s === 'REJECTED') return `<div class="card"><div class="note err"><b>Банк не может предложить финансирование</b><ul class="l">${(dec?.reasons || []).map(r => `<li>${esc(r)}</li>`).join('')}</ul></div>${bank() ? '' : '<button data-act="new">Подать новую заявку</button>'}</div>`;
  return `<div class="card"><b>${ST[s][0]}</b></div>`;
}
function decisionForm(a) {
  return `<div class="card" style="border:2px solid var(--pur)"><h2>Решение андеррайтера</h2><p class="sub">Рекомендация системы: ${(a.decision?.reasons || []).map(esc).join('; ')}</p>
  ${[['approve', 'Одобрить на запрошенных условиях'], ['counter', 'Предложить другие условия'], ['request_info', 'Запросить информацию у клиента'], ['reject', 'Отказать']].map((x, i) => `<label class="chk" style="margin:6px 0"><input type="radio" name="act" value="${x[0]}" ${i ? '' : 'checked'}>${x[1]}</label>`).join('')}
  <div class="row"><div><label>Сумма (для «другие условия»)</label><input id="d-am" type="number" value="${a.amount}"></div><div><label>Срок, мес.</label><input id="d-tm" type="number" value="${a.term_months}"></div></div>
  <label>Комментарий (обязателен для отказа и запроса информации)</label><textarea id="d-cm" rows="2"></textarea><p><button class="pur" data-act="decide" data-id="${a.id}">Принять решение</button></p></div>`;
}
function bankData(a) {
  if (!bank() || !a.checks) return '';
  const e = a.checks.egrul, b = a.checks.bki, f = a.checks.fns, sc = a.scoring;
  return `<div class="card"><h2>Данные из источников <small style="color:var(--mut);font-weight:400">(симуляторы)</small></h2><div class="row">
  <div><b>ЕГРЮЛ/ЕГРИП</b><p class="sub">${esc(e.name)}<br>Статус: ${e.status === 'ACTIVE' ? 'действует' : '<span class="neg">' + e.status + '</span>'}<br>Рег.: ${e.reg_date}<br>${esc(e.okved)}<br>Руководитель: ${esc(e.head)}</p></div>
  <div><b>БКИ</b><p class="sub">История: ${b.history_months} мес.<br>Активных кредитов: ${b.active_loans}<br>Долг: ${rub(b.total_debt)}<br>Текущая просрочка: ${b.overdue_now ? '<span class="neg">да</span>' : 'нет'}<br>Макс. просрочка 12 мес.: ${b.max_delay_days_12m} дн.</p></div>
  <div><b>ФНС «Прозрачный бизнес»</b><p class="sub">Налоговая задолженность: ${f.tax_arrears ? '<span class="neg">есть</span>' : 'нет'}<br>Массовый адрес: ${f.mass_address ? 'да' : 'нет'}<br>Массовый руководитель: ${f.mass_director ? 'да' : 'нет'}<br>Дисквалификация: ${f.disqualified ? 'да' : 'нет'}</p></div></div></div>
  <div class="card"><div class="between"><h2 style="margin:0">Скоринг (${sc.model})</h2><span class="big">${sc.score} <small style="font-size:16px">класс ${sc.grade}</small></span></div><table><tr><th>Фактор</th><th>Значение</th><th class="r">Баллы</th></tr><tr><td>Базовая оценка</td><td></td><td class="r">500</td></tr>
  ${sc.factors.map(x => `<tr><td>${esc(x.factor)}</td><td>${esc(x.value)}</td><td class="r ${x.points > 0 ? 'pos' : x.points < 0 ? 'neg' : ''}">${x.points > 0 ? '+' : ''}${x.points}</td></tr>`).join('')}</table></div>`;
}
async function detailView(id) {
  if (!S.products.length) S.products = await api('/products');
  const [a, ev] = await Promise.all([api('/applications/' + id), api('/applications/' + id + '/events')]);
  S.sig = 'D' + a.id + a.version;
  const cur = STEP_OF[a.status], stop = ['REJECTED', 'DECLINED', 'CANCELLED', 'INFO_REQUESTED'].includes(a.status);
  $('#app').innerHTML = `<p><a data-act="home">← ${bank() ? 'К очереди' : 'К заявкам'}</a></p><div class="between"><div><h1>${esc(PN(a.product))}</h1><p class="sub">Заявка ${a.id} · ${esc(a.company?.name || '')}</p></div>${badge(a.status)}</div>
  <div class="card"><div class="steps ${stop ? 'stop' : ''}">${STEPS.map((t, i) => `<div class="${i < cur ? 'done' : i === cur ? 'act' : ''}"><i></i>${t}</div>`).join('')}</div></div>
  ${actionPanel(a)}${bankData(a)}
  <div class="card"><h2>Параметры заявки</h2><div class="kv">${kv('Сумма', rub(a.amount || 0))}${kv('Срок', a.term_months + ' мес.')}${kv('Цель', esc(a.purpose || '—'))}${kv('ИНН', esc(a.company?.inn || '—'))}${kv('Представитель', esc(a.company?.contact_name || '—') + ', ' + esc(a.company?.contact_role || ''))}${kv('Выручка / прибыль', rub(a.financials?.revenue_year || 0) + ' / ' + rub(a.financials?.profit_year || 0))}${kv('Платежи по кредитам', rub(a.financials?.monthly_obligations || 0) + '/мес.')}${kv('Документы', (a.documents || []).map(d => esc(d.name)).join(', ') || 'нет')}</div></div>
  <div class="card"><h2>История заявки</h2><div class="tl">${ev.slice().reverse().map(e => `<div><b>${ST[e.to_status][0]}</b> · ${esc(e.actor)}<br><small>${dt(e.ts)}${e.comment ? ' — ' + esc(e.comment) : ''}</small></div>`).join('')}</div></div>`;
}

// ---------- действия ----------
const A = {
  home() { location.hash = '#/'; render(); },
  logout, new() { S.W = null; location.hash = '#/new'; render(); },
  fill(t) { $('#lg').value = t.dataset.u; $('#pw').value = 'Demo#2026'; },
  async login() { try { const r = await api('/auth/login', { method: 'POST', body: { login: $('#lg').value, password: $('#pw').value } }); S.token = r.token; S.user = r.user; localStorage.setItem('token', r.token); localStorage.setItem('user', JSON.stringify(r.user)); location.hash = '#/'; render(); } catch (e) { toast(e.message, true); } },
  filter(t) { S.filter = t.dataset.s; render(); },
  open(t) { location.hash = '#/app/' + t.dataset.id; },
  edit(t) { S.W = null; location.hash = '#/edit/' + t.dataset.id; render(); },
  pick(t) { const p = S.products.find(x => x.id === t.dataset.id); S.W.d.product = p.id; S.W.d.amount = p.min_amount * 4 > p.max_amount ? p.min_amount : p.min_amount * 4; S.W.d.term_months = Math.min(p.max_term, Math.max(p.min_term, 12)); render(); },
  goto(t) { S.W.step = +t.dataset.i; render(); }, next() { S.W.step++; render(); }, prev() { S.W.step--; render(); },
  fillinn(t) { S.W.d.company.inn = t.dataset.v; render(); },
  rmdoc(t) { S.W.d.documents.splice(+t.dataset.i, 1); render(); },
  async lookup() {
    try { const r = await api('/registry/lookup?inn=' + encodeURIComponent(S.W.d.company.inn || '')); Object.assign(S.W.d.company, { name: r.name, okved: r.okved, contact_name: S.W.d.company.contact_name || r.head }); await render(); $('#lk').innerHTML = `<div class="note ok">Найдено: <b>${esc(r.name)}</b> · ${r.status === 'ACTIVE' ? 'действует' : 'статус ' + esc(r.status)}</div>`; } catch (e) { toast(e.message, true); }
  },
  async save() { try { await saveDraft(); toast('Черновик сохранён'); } catch (e) { toast(e.message, true); } },
  async send() {
    if (!S.W.d.consent) return toast('Нужно согласие на обработку данных', true);
    try { await saveDraft(); const id = S.W.id; await api(`/applications/${id}/submit`, { method: 'POST', body: {} }); S.W = null; location.hash = '#/app/' + id; render(); } catch (e) { toast(e.message, true); }
  },
  async accept(t) { await act(t, 'offer/accept'); }, async decline(t) { if (confirm('Отказаться от предложения банка?')) await act(t, 'offer/decline'); },
  async cancel(t) { if (confirm('Отозвать заявку?')) await act(t, 'cancel'); },
  async sign(t) { if (!$('#sg').checked) return toast('Подтвердите ознакомление с договором', true); await act(t, 'sign'); },
  async decide(t) {
    const action = $('input[name=act]:checked').value;
    try { await api('/bank/applications/' + t.dataset.id + '/decision', { method: 'POST', body: { action, amount: num($('#d-am').value), term_months: num($('#d-tm').value), comment: $('#d-cm').value || null } }); toast('Решение сохранено'); render(); } catch (e) { toast(e.message, true); }
  },
};
async function act(t, path) { try { await api(`/applications/${t.dataset.id}/${path}`, { method: 'POST' }); render(); } catch (e) { toast(e.message, true); } }
document.addEventListener('click', e => { const t = e.target.closest('[data-act]'); if (t && A[t.dataset.act]) { e.preventDefault(); A[t.dataset.act](t); } });
document.addEventListener('input', e => {
  const t = e.target; if (!t.dataset.k || !S.W) return;
  setPath(t.dataset.k, t.dataset.b ? t.checked : t.dataset.n ? num(t.value) : t.value); if (t.dataset.k === 'amount' || t.dataset.k === 'term_months') calc();
});
document.addEventListener('change', e => { if (e.target.id === 'df' && e.target.files[0]) { S.W.d.documents.push({ name: e.target.files[0].name.slice(0, 200), kind: $('#dk').value }); render(); } });
document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'pw') A.login(); });

// живое обновление статусов без перезагрузки страницы
setInterval(async () => {
  if (!S.token || S.W || document.hidden) return;
  const h = location.hash || '#/'; if (h === '#/login' || h.startsWith('#/new') || h.startsWith('#/edit')) return;
  try {
    let sig;
    if (h.startsWith('#/app/')) { const a = await api('/applications/' + h.slice(6)); sig = 'D' + a.id + a.version; }
    else { const q = bank() && S.filter ? '?status=' + S.filter : ''; const [apps, st] = await Promise.all([api('/applications' + q), bank() ? api('/bank/stats') : null]); sig = 'L' + JSON.stringify(apps.map(a => [a.id, a.version])) + JSON.stringify(st); }
    if (sig !== S.sig) render();
  } catch (e) { /* сетевые сбои игнорируем, повторим на следующем тике */ }
}, 2000);
if (!location.hash) location.hash = S.token ? '#/' : '#/login';
render();
