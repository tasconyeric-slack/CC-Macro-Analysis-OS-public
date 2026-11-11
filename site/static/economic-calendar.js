/* Progressive enhancement for the official release calendar.
   Events originate in the server-rendered official calendar; no synthetic dates. */
(() => {
  const root = document.querySelector('[data-calendar-root]');
  if (!root || root.dataset.calendarReady) return;
  root.dataset.calendarReady = 'true';
  const list = root.querySelector('[data-calendar-source]');
  const grid = root.querySelector('[data-calendar-grid]');
  const agenda = root.querySelector('[data-calendar-agenda]');
  const input = root.querySelector('[data-calendar-month]');
  const language = root.dataset.locale === 'zh' ? 'zh' : 'en';
  const today = root.dataset.today;
  const original = Array.from(list.querySelectorAll('[data-calendar-event]'));
  const events = original.map(node => ({
    date: node.dataset.date,
    time: node.dataset.time,
    node
  }));
  const months = {};
  for (const event of events) {
    (months[event.date] ||= []).push(event);
  }
  // Timed releases first, in Beijing order; date-only publications close the day.
  for (const day of Object.values(months)) day.sort((a, b) => (a.time || '99:99').localeCompare(b.time || '99:99'));
  const upcoming = events.map(event => event.date).filter(date => date >= today).sort();
  let selected = months[today] ? today : (upcoming.find(date => date.slice(0, 7) === today.slice(0, 7)) || today);

  function cloneEvent(event, compact) {
    const item = event.node.cloneNode(true);
    item.removeAttribute('id');
    const name = item.querySelector('.desk-calendar-name a');
    if (name && compact && name.dataset.short) {
      name.title = name.textContent.trim();
      name.textContent = name.dataset.short;
    }
    return item;
  }

  function showAgenda() {
    agenda.replaceChildren();
    const label = document.createElement('h3');
    const parts = selected.split('-').map(Number);
    label.textContent = language === 'zh'
      ? parts[1] + '月' + parts[2] + '日'
      : new Date(Date.UTC(parts[0], parts[1] - 1, parts[2])).toLocaleDateString('en-US', {month:'short',day:'numeric',timeZone:'UTC'});
    agenda.append(label);
    const daily = months[selected] || [];
    if (!daily.length) {
      const none = document.createElement('p');
      none.className = 'muted';
      none.textContent = '—';
      agenda.append(none);
    } else {
      daily.forEach(event => agenda.append(cloneEvent(event, false)));
    }
    root.querySelectorAll('[data-calendar-day]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.calendarDay === selected));
    });
  }

  function render() {
    const yearMonth = input.value.match(/^(\d{4})-(\d{2})$/);
    if (!yearMonth) return;
    const year = Number(yearMonth[1]), month = Number(yearMonth[2]);
    if (month < 1 || month > 12) return;
    const count = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const offset = (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
    grid.replaceChildren();
    if (!selected.startsWith(input.value)) {
      const firstEvent = events.find(event => event.date.startsWith(input.value));
      selected = firstEvent ? firstEvent.date : input.value + '-01';
    }
    for (let offsetDay = 0; offsetDay < offset; offsetDay++) {
      const spacer = document.createElement('div');
      spacer.className = 'desk-calendar-cell desk-calendar-blank';
      spacer.setAttribute('aria-hidden', 'true');
      grid.append(spacer);
    }
    for (let day = 1; day <= count; day++) {
      const date = input.value + '-' + String(day).padStart(2, '0');
      const cell = document.createElement('div');
      cell.className = 'desk-calendar-cell';
      if (date === today) cell.classList.add('is-today');
      if (months[date]?.length) cell.classList.add('has-events');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'desk-calendar-day';
      btn.dataset.calendarDay = date;
      btn.textContent = String(day);
      btn.setAttribute('aria-label', date);
      btn.addEventListener('click', () => { selected = date; showAgenda(); });
      cell.append(btn);
      const content = document.createElement('div');
      content.className = 'desk-calendar-items';
      (months[date] || []).forEach(event => content.append(cloneEvent(event, true)));
      cell.append(content);
      const counter = document.createElement('span');
      counter.className = 'desk-calendar-count';
      counter.textContent = (months[date] || []).length ? String(months[date].length) : '';
      counter.setAttribute('aria-hidden', 'true');
      cell.append(counter);
      grid.append(cell);
    }
    showAgenda();
  }

  function changeMonth(delta) {
    const m = input.value.match(/^(\d{4})-(\d{2})$/);
    if (!m) return;
    const value = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1 + delta, 1));
    input.value = value.getUTCFullYear() + '-' + String(value.getUTCMonth() + 1).padStart(2, '0');
    render();
  }

  root.querySelector('[data-calendar-prev]').addEventListener('click', () => changeMonth(-1));
  root.querySelector('[data-calendar-next]').addEventListener('click', () => changeMonth(1));
  input.addEventListener('change', render);
  if (!input.value) input.value = today.slice(0, 7);
  render();
  root.classList.add('calendar-enhanced');
})();
