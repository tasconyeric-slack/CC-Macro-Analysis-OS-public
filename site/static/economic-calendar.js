/* Progressive enhancement for the China release calendar.
   Events come from the server-rendered list (official releases and dated news / policy occurrences);
   no synthetic dates. Month cells carry names, times and state only; readings open on click or tap. */
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
  const events = Array.from(list.querySelectorAll('[data-calendar-event]')).map(node => ({
    date: node.dataset.date, time: node.dataset.time, status: node.dataset.status, node
  }));
  const days = {};
  for (const event of events) (days[event.date] ||= []).push(event);
  // Timed events first, in Beijing order; date-only items close the day.
  for (const day of Object.values(days)) day.sort((a, b) => (a.time || '99:99').localeCompare(b.time || '99:99'));
  const upcoming = events.map(event => event.date).filter(date => date >= today).sort();
  let selected = days[today] ? today : (upcoming.find(date => date.slice(0, 7) === today.slice(0, 7)) || today);
  const statusText = {released: language === 'zh' ? '已发布' : 'Released', upcoming: language === 'zh' ? '即将发布' : 'Upcoming'};

  function chip(event, tag) {
    const name = event.node.querySelector('.desk-calendar-name');
    const button = document.createElement(tag);
    button.className = 'desk-calendar-chip';
    button.dataset.status = event.status;
    if (tag === 'button') button.type = 'button';
    const dot = document.createElement('i');
    dot.setAttribute('aria-hidden', 'true');
    button.append(dot);
    if (event.time) {
      const time = document.createElement('time');
      time.textContent = event.time;
      button.append(time);
    }
    const label = document.createElement('span');
    label.textContent = name.dataset.short || name.textContent.trim();
    if (name.lang) label.lang = name.lang;
    button.append(label);
    button.title = name.textContent.trim();
    button.setAttribute('aria-label', [event.time, name.textContent.trim(), statusText[event.status]].filter(Boolean).join(' '));
    return button;
  }

  function detail(event) {
    const box = document.createElement('div');
    box.className = 'desk-calendar-card';
    const head = event.node.querySelector('.desk-calendar-name').cloneNode(true);
    head.removeAttribute('data-short');
    const when = document.createElement('p');
    when.className = 'desk-calendar-when';
    when.textContent = event.date + (event.time ? ' ' + event.time : '');
    box.append(head, when, event.node.querySelector('.desk-calendar-detail').cloneNode(true));
    return box;
  }

  // ---- desktop: one popover, opened by click, Enter or Space; closed by Escape, outside click or ×
  const pop = document.createElement('div');
  pop.className = 'desk-calendar-popover';
  pop.setAttribute('role', 'dialog');
  pop.hidden = true;
  root.append(pop);
  let opener = null;

  function closePopover() {
    if (pop.hidden) return;
    pop.hidden = true;
    pop.replaceChildren();
    if (opener) opener.setAttribute('aria-expanded', 'false');
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  }

  function openPopover(event, button) {
    if (opener === button) { closePopover(); return; }
    closePopover();
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'desk-calendar-close';
    close.setAttribute('aria-label', language === 'zh' ? '关闭' : 'Close');
    close.textContent = '×';
    close.addEventListener('click', closePopover);
    pop.append(close, detail(event));
    pop.setAttribute('aria-label', button.title);
    pop.hidden = false;
    const box = root.getBoundingClientRect(), at = button.getBoundingClientRect();
    const width = Math.min(360, box.width - 16);
    pop.style.width = width + 'px';
    pop.style.left = Math.max(8, Math.min(at.left - box.left, box.width - width - 8)) + 'px';
    pop.style.top = (at.bottom - box.top + 6) + 'px';
    opener = button;
    button.setAttribute('aria-expanded', 'true');
    close.focus();
  }

  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePopover(); });
  document.addEventListener('click', e => {
    if (!pop.hidden && !pop.contains(e.target) && !e.target.closest('.desk-calendar-chip')) closePopover();
  });

  // ---- mobile: the selected day's agenda; tap an event to expand its readings
  function showAgenda() {
    agenda.replaceChildren();
    const label = document.createElement('h3');
    const parts = selected.split('-').map(Number);
    label.textContent = language === 'zh'
      ? parts[1] + '月' + parts[2] + '日'
      : new Date(Date.UTC(parts[0], parts[1] - 1, parts[2])).toLocaleDateString('en-US', {month: 'short', day: 'numeric', timeZone: 'UTC'});
    agenda.append(label);
    const daily = days[selected] || [];
    if (!daily.length) {
      const none = document.createElement('p');
      none.className = 'muted';
      none.textContent = '—';
      agenda.append(none);
    }
    daily.forEach(event => {
      const row = document.createElement('div');
      row.className = 'desk-calendar-agenda-item';
      const button = chip(event, 'button');
      button.setAttribute('aria-expanded', 'false');
      const body = detail(event);
      body.hidden = true;
      button.addEventListener('click', () => {
        body.hidden = !body.hidden;
        button.setAttribute('aria-expanded', String(!body.hidden));
      });
      row.append(button, body);
      agenda.append(row);
    });
    root.querySelectorAll('[data-calendar-day]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.calendarDay === selected));
    });
  }

  function render() {
    closePopover();
    const yearMonth = input.value.match(/^(\d{4})-(\d{2})$/);
    if (!yearMonth) return;
    const year = Number(yearMonth[1]), month = Number(yearMonth[2]);
    if (month < 1 || month > 12) return;
    const count = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const offset = (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
    grid.replaceChildren();
    if (!selected.startsWith(input.value)) {
      const first = events.find(event => event.date.startsWith(input.value));
      selected = first ? first.date : input.value + '-01';
    }
    for (let i = 0; i < offset; i++) {
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
      if (days[date]?.length) cell.classList.add('has-events');
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
      (days[date] || []).forEach(event => {
        const button = chip(event, 'button');
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-haspopup', 'dialog');
        button.addEventListener('click', e => { e.stopPropagation(); selected = date; openPopover(event, button); });
        content.append(button);
      });
      cell.append(content);
      const counter = document.createElement('span');
      counter.className = 'desk-calendar-count';
      counter.textContent = (days[date] || []).length ? String(days[date].length) : '';
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
