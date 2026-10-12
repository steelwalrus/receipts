// Receipts UI. Plain DOM, no build step.

const main = document.getElementById('main');
const drawer = document.getElementById('drawer');

let meta = null;          // /api/overview
let timeline = null;      // /api/timeline
let token = '';
let animateStrip = true;
let profile = null;
const filters = { q: '', role: '', competency: '', tag: '' };

const STORY_LABELS = {
  when: 'a date', role: 'the role', competencies: 'competencies', situation: 'the situation',
  action: 'what you did', result: 'the result', impact: 'the impact',
};
const STRENGTHS = { 1: 'Minor', 2: 'Solid', 3: 'Headline story' };

// -- small helpers -----------------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'style') node.style.cssText = value; // CSSOM, so the strict CSP allows it
    else node.setAttribute(key, value === true ? '' : value);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'style') node.style.cssText = value;
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

async function api(path, { method = 'GET', body } = {}) {
  const response = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json', 'X-Receipts-Token': token } : { 'X-Receipts-Token': token },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

let toastTimer;
function toast(message, error = false) {
  const node = document.getElementById('toast');
  node.textContent = message;
  node.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.className = 'toast'; }, error ? 6000 : 2600);
}

function partialToDate(value, end = false) {
  const [y, m, d] = value.split('-').map(Number);
  if (!end) return new Date(y, (m || 1) - 1, d || 1);
  if (d) return new Date(y, m - 1, d);
  if (m) return new Date(y, m, 0);
  return new Date(y, 11, 31);
}

function yearsOf(date) {
  return date.getFullYear() + (date - new Date(date.getFullYear(), 0, 1)) / 31_557_600_000;
}

function duration(months) {
  const years = Math.floor(months / 12);
  const rest = months % 12;
  const parts = [];
  if (years) parts.push(`${years} year${years === 1 ? '' : 's'}`);
  if (rest) parts.push(`${rest} month${rest === 1 ? '' : 's'}`);
  return parts.join(', ');
}

function plural(n, word) {
  if (n === 1) return `${n} ${word}`;
  return `${n} ${word.endsWith('y') ? `${word.slice(0, -1)}ies` : `${word}s`}`;
}

function competencyName(slug) {
  return meta.competencies.find((c) => c.slug === slug)?.name || slug;
}

function ticks(entry) {
  const parts = Object.keys(STORY_LABELS);
  const missing = new Set(entry.missing);
  const done = parts.length - missing.size;
  const label = missing.size ? `Missing ${[...missing].map((m) => STORY_LABELS[m]).join(', ')}` : 'Complete';
  return el('span', { class: 'ticks', title: label, 'aria-label': `${done} of ${parts.length} story parts. ${label}`, role: 'img' },
    parts.map((p) => el('i', { class: missing.has(p) ? 'off' : '' })));
}

// -- data --------------------------------------------------------------------

async function refresh() {
  [meta, timeline] = await Promise.all([api('/api/overview'), api('/api/timeline')]);
  token = meta.token;
  if (!profile) profile = meta.profiles.find((p) => p.slug === 'head-of-engineering')?.slug || meta.profiles[0]?.slug || null;
}

// -- routing -----------------------------------------------------------------

function route() {
  const [view, query] = (location.hash.slice(1) || 'timeline').split('?');
  if (query) {
    const params = new URLSearchParams(query);
    for (const key of Object.keys(filters)) filters[key] = params.get(key) || '';
  }
  return ['timeline', 'entries', 'coverage'].includes(view) ? view : 'timeline';
}

async function render() {
  const view = route();
  document.querySelectorAll('.bar nav a').forEach((a) => {
    if (a.dataset.view === view) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  const content = view === 'entries' ? await entriesView() : view === 'coverage' ? coverageView() : timelineView();
  main.replaceChildren(content);
  document.title = `${view[0].toUpperCase()}${view.slice(1)} – Receipts`;
}

// -- timeline ----------------------------------------------------------------

function timelineView() {
  const roles = timeline.roles;
  const entryCount = meta.stats.entries;
  const head = el('div', { class: 'page-head' },
    el('div', {},
      el('h1', { text: 'Timeline' }),
      roles.length ? el('p', { class: 'lede' }, summaryLine()) : null),
    el('button', { class: 'button', type: 'button', onclick: () => roleForm() }, 'Add role'));

  if (!roles.length && !entryCount) {
    return el('div', {}, head, el('div', { class: 'empty' },
      el('p', { text: 'No roles yet. Add the roles you have held with rough dates, then add entries to them.' }),
      el('p', { class: 'hint', text: 'Or start a capture session in Claude or Codex and talk it through. See the README for setup.' })));
  }

  const sections = [...roles].reverse().map(roleSection);
  if (timeline.unplaced.length) {
    sections.push(el('section', { class: 'role', id: 'role-none' },
      el('div', { class: 'role-head' }, el('div', {}, el('h2', { text: 'Not on the timeline yet' }))),
      el('p', { class: 'role-summary', text: 'These entries have no role. Give them a date or pick a role to place them.' }),
      el('ul', { class: 'rows' }, timeline.unplaced.map((e) => entryRow(e)))));
  }
  return el('div', {}, head, roles.length ? careerStrip(roles) : null, sections);
}

function summaryLine() {
  const roles = timeline.roles;
  const first = partialToDate(roles[0].started);
  const years = Math.max(1, Math.round((Date.now() - first) / 31_557_600_000));
  const { entries, competencies_covered: covered, competencies } = meta.stats;
  return [
    'Since ', el('strong', { text: String(first.getFullYear()) }), `: ${plural(roles.length, 'role')} over ${plural(years, 'year')}. `,
    el('strong', { text: plural(entries, 'entry') }),
    ` cover ${covered} of ${competencies} competencies.`,
  ];
}

function careerStrip(roles) {
  const wrap = el('div', { class: `strip${animateStrip ? ' animate' : ''}` });
  animateStrip = false;
  const width = Math.max(320, Math.min(main.clientWidth, 1148) - 42);
  const narrow = width < 600;
  const gutter = narrow ? 0 : Math.min(250, width * 0.27);
  const laneH = narrow ? 46 : 34;
  const barH = 16;
  const top = 6;
  const ordered = [...roles].reverse(); // newest at the top, so the career climbs to the right

  const starts = roles.map((r) => yearsOf(partialToDate(r.started)));
  const ends = roles.map((r) => (r.ended ? yearsOf(partialToDate(r.ended, true)) : yearsOf(new Date())));
  const x0 = Math.floor(Math.min(...starts));
  const x1 = Math.ceil(Math.max(...ends) + 0.15);
  const plot = width - gutter;
  const x = (years) => gutter + ((years - x0) / (x1 - x0)) * plot;
  const height = top + ordered.length * laneH + 26;

  const chart = svg('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Roles over time' });
  const step = Math.max(1, Math.ceil((x1 - x0) / (plot / 70))); // keep year labels ~70px apart
  for (let year = x0; year <= x1; year += 1) {
    chart.append(svg('line', { class: 'grid', x1: x(year), x2: x(year), y1: 0, y2: height - 22 }));
    if ((year - x0) % step === 0) {
      const anchor = year === x0 && narrow ? 'start' : year === x1 && narrow ? 'end' : 'middle';
      chart.append(svg('text', { class: 'year', x: x(year), y: height - 6, 'text-anchor': anchor }, String(year)));
    }
  }

  ordered.forEach((role, i) => {
    const y = top + i * laneH + (narrow ? 20 : (laneH - barH) / 2);
    const start = x(yearsOf(partialToDate(role.started)));
    const end = x(role.ended ? yearsOf(partialToDate(role.ended, true)) : yearsOf(new Date()));
    const lane = svg('g', {
      class: `lane${role.ended ? '' : ' current'}`, tabindex: 0, role: 'link',
      'aria-label': `${role.title}${role.organisation ? `, ${role.organisation}` : ''}, ${role.label}`,
      onclick: () => document.getElementById(`role-${role.id}`)?.scrollIntoView({ behavior: 'smooth' }),
      onkeydown: (event) => { if (event.key === 'Enter') event.currentTarget.dispatchEvent(new MouseEvent('click')); },
    });
    const labelY = narrow ? y - 6 : y + barH / 2 + 4.5;
    const label = svg('text', { class: 'lane-label', x: narrow ? Math.min(start, width - 160) : 0, y: labelY }, role.title);
    if (!narrow && role.organisation) label.append(svg('tspan', { class: 'lane-org', dx: 6 }, role.organisation));
    lane.append(
      svg('rect', { class: 'band', x: start, y, width: Math.max(4, end - start), height: barH, rx: 3, style: `--i:${ordered.length - 1 - i}` }),
      label,
      svg('title', {}, `${role.title}, ${role.label}`),
    );
    // Entries that land within a few pixels of each other (often "c. 2022") share one numbered mark.
    const groups = [];
    for (const entry of role.entries.filter((e) => e.happened_from)) {
      const from = yearsOf(partialToDate(entry.happened_from));
      const to = entry.happened_to ? yearsOf(partialToDate(entry.happened_to, true)) : from;
      const cx = Math.min(end - 3, Math.max(start + 3, x((from + to) / 2)));
      const group = groups.find((g) => Math.abs(g.cx - cx) < 10);
      if (group) group.entries.push(entry);
      else groups.push({ cx, entries: [entry] });
    }
    for (const { cx, entries } of groups) {
      const single = entries.length === 1;
      const headline = entries.some((e) => e.strength === 3);
      const mark = svg('g', {
        style: `--i:${ordered.length - 1 - i}`,
        onclick: (event) => {
          event.stopPropagation();
          if (single) showEntry(entries[0].id);
          else document.getElementById(`role-${role.id}`)?.scrollIntoView({ behavior: 'smooth' });
        },
      },
      svg('circle', { class: `mark${headline ? ' headline' : ''}`, cx, cy: y + barH / 2, r: single ? (headline ? 5.5 : 4.5) : 8 }),
      svg('title', {}, entries.map((e) => `${e.title} (${e.when})`).join('\n')));
      if (!single) {
        mark.append(svg('text', { class: 'mark-count', x: cx, y: y + barH / 2 + 3.5, 'text-anchor': 'middle' }, String(entries.length)));
      }
      lane.append(mark);
    }
    chart.append(lane);
  });
  wrap.append(chart);
  return wrap;
}

function newestFirst(entries) {
  // The timeline API sorts oldest first with undated entries last; keep undated ones at the bottom.
  return [...entries.filter((e) => e.happened_from).reverse(), ...entries.filter((e) => !e.happened_from)];
}

function roleSection(role) {
  return el('section', { class: 'role', id: `role-${role.id}` },
    el('div', { class: 'role-head' },
      el('div', {}, el('h2', { text: role.title }), role.organisation ? el('div', { class: 'org', text: role.organisation }) : null),
      el('div', { class: 'role-dates' }, el('b', { text: role.label }), duration(role.months))),
    role.summary ? el('p', { class: 'role-summary', text: role.summary }) : null,
    role.entries.length
      ? el('ul', { class: 'rows' }, newestFirst(role.entries).map((e) => entryRow(e)))
      : el('div', { class: 'empty' }, el('p', { class: 'hint', text: 'No entries for this role yet.' })),
    el('div', { class: 'role-tools' },
      el('button', { class: 'link-button', type: 'button', onclick: () => entryForm(null, { role_id: role.id }) }, 'Add entry to this role'),
      el('button', { class: 'link-button', type: 'button', onclick: () => roleForm(role) }, 'Edit role')));
}

function entryRow(entry, { showRole = false } = {}) {
  const flag = entry.strength === 3 ? el('span', { class: 'headline-flag', text: 'Headline' })
    : entry.strength === 1 ? el('span', { class: 'minor-flag', text: 'Minor' }) : null;
  return el('li', { class: 'row' },
    el('div', { class: 'row-when', text: entry.when || 'No date' }),
    el('div', {},
      el('button', { class: 'row-title', type: 'button', onclick: () => showEntry(entry.id) }, entry.title),
      entry.summary ? el('p', { class: 'row-summary', text: entry.summary }) : null,
      el('div', { class: 'row-meta' },
        showRole && entry.role ? el('span', { class: 'chip', text: entry.role.title }) : null,
        entry.competencies.map((slug) => el('button', {
          class: 'chip', type: 'button', title: 'Show entries with this competency',
          onclick: () => { location.hash = `entries?competency=${slug}`; },
        }, competencyName(slug))),
        entry.tags.map((t) => el('span', { class: 'chip tag', text: t })))),
    el('div', { class: 'row-side' }, ticks(entry), flag));
}

// -- entries -------------------------------------------------------------------

async function entryResults() {
  const query = hashQuery();
  const entries = await api(`/api/entries${query}`);
  return [
    el('p', { class: 'count', text: plural(entries.length, 'entry') }),
    entries.length
      ? el('ul', { class: 'rows' }, entries.map((e) => entryRow(e, { showRole: true })))
      : el('div', { class: 'empty' }, el('p', { text: query ? 'Nothing matches these filters.' : 'No entries yet.' })),
  ];
}

async function entriesView() {
  const results = el('div', {}, ...(await entryResults()));

  let debounce;
  const update = (key, value) => {
    filters[key] = value;
    clearTimeout(debounce);
    debounce = setTimeout(async () => {
      history.replaceState(null, '', `#entries${hashQuery()}`);
      try { results.replaceChildren(...(await entryResults())); } catch (error) { toast(error.message, true); }
    }, key === 'q' ? 220 : 0);
  };

  const areas = [...new Set(meta.competencies.map((c) => c.area))];
  const search = el('input', {
    type: 'search', id: 'filter-q', placeholder: 'Search titles, stories and tags', value: filters.q, 'aria-label': 'Search entries',
    oninput: (event) => update('q', event.target.value),
  });
  const roleSelect = el('select', { id: 'filter-role', 'aria-label': 'Role', onchange: (event) => update('role', event.target.value) },
    el('option', { value: '' }, 'All roles'),
    [...meta.roles].reverse().map((r) => el('option', { value: r.id, selected: String(r.id) === filters.role }, r.title)));
  const compSelect = el('select', { id: 'filter-competency', 'aria-label': 'Competency', onchange: (event) => update('competency', event.target.value) },
    el('option', { value: '' }, 'All competencies'),
    areas.map((area) => el('optgroup', { label: area },
      meta.competencies.filter((c) => c.area === area).map((c) =>
        el('option', { value: c.slug, selected: c.slug === filters.competency }, `${c.name} (${c.entry_count})`)))));
  const tagSelect = meta.tags.length ? el('select', { id: 'filter-tag', 'aria-label': 'Tag', onchange: (event) => update('tag', event.target.value) },
    el('option', { value: '' }, 'All tags'),
    meta.tags.map((t) => el('option', { value: t.tag, selected: t.tag === filters.tag }, `${t.tag} (${t.entry_count})`))) : null;
  const active = Object.values(filters).some(Boolean);

  return el('div', {},
    el('div', { class: 'page-head' }, el('div', {}, el('h1', { text: 'Entries' }))),
    el('div', { class: 'filters' }, search, roleSelect, compSelect, tagSelect,
      active ? el('button', {
        class: 'link-button', type: 'button',
        onclick: () => { Object.keys(filters).forEach((k) => { filters[k] = ''; }); location.hash = 'entries'; render(); },
      }, 'Clear filters') : null),
    results);
}

function hashQuery() {
  const params = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
  return params.toString() ? `?${params}` : '';
}

// -- coverage --------------------------------------------------------------------

async function loadCoverage() {
  return api(`/api/coverage${profile ? `?profile=${encodeURIComponent(profile)}` : ''}`);
}

function coverageView() {
  const holder = el('div', {}, el('div', { class: 'page-head' }, el('div', {},
    el('h1', { text: 'Coverage' }),
    el('p', { class: 'lede', text: 'How many entries show each competency in each role. Pick a target role to see what is covered, thin or missing.' }))));
  loadCoverage().then((data) => holder.append(...coverageBody(data))).catch((error) => toast(error.message, true));
  return holder;
}

function coverageBody(data) {
  const picker = el('div', { class: 'profiles', role: 'group', 'aria-label': 'Target role' },
    meta.profiles.map((p) => el('button', {
      type: 'button', 'aria-pressed': String(p.slug === profile),
      onclick: () => { profile = p.slug === profile ? null : p.slug; render(); },
    }, p.name)));

  const need = {};
  let score = null;
  if (data.profile) {
    for (const c of data.profile.competencies) need[c.slug] = c;
    const s = data.profile.score;
    score = el('div', { class: 'score' },
      el('div', {}, el('b', { text: `${s.core_covered}/${s.core_total}` }), 'core competencies covered'),
      el('div', { class: s.core_thin ? 'meh' : '' }, el('b', { text: String(s.core_thin) }), 'thin'),
      el('div', { class: s.core_missing ? 'bad' : '' }, el('b', { text: String(s.core_missing) }), 'missing'));
  }

  const roles = data.roles;
  const hasNone = data.competencies.some((c) => c.by_role.none);
  const columns = [...roles.map((r) => ({ key: String(r.id), title: r.title, sub: r.organisation })),
    ...(hasNone ? [{ key: 'none', title: 'No role', sub: '' }] : [])];

  const head = el('tr', {},
    el('th', { scope: 'col' }, 'Competency'),
    columns.map((c) => el('th', { scope: 'col' }, c.title, c.sub ? el('small', { text: c.sub }) : null)),
    el('th', { scope: 'col' }, 'Total'),
    data.profile ? el('th', { scope: 'col' }, data.profile.name) : null);

  const body = [];
  let area = null;
  for (const comp of data.competencies) {
    if (comp.area !== area) {
      area = comp.area;
      body.push(el('tr', { class: 'area' }, el('th', { colspan: columns.length + 2 + (data.profile ? 1 : 0), scope: 'colgroup', text: area })));
    }
    const target = need[comp.slug];
    const rowClass = data.profile ? (target ? (target.core ? 'is-core' : '') : 'not-needed') : '';
    body.push(el('tr', { class: rowClass },
      el('th', { scope: 'row', title: comp.description }, comp.name),
      columns.map((col) => {
        const count = comp.by_role[col.key] || 0;
        if (!count) return el('td', { class: 'cell zero' });
        return el('td', { class: 'cell' }, el('button', {
          type: 'button', style: `--v:${Math.min(85, 18 + count * 20)}`,
          title: `${plural(count, 'entry')}: ${comp.name}, ${col.title}`,
          onclick: () => { location.hash = `entries?competency=${comp.slug}${col.key === 'none' ? '' : `&role=${col.key}`}`; },
        }, String(count)));
      }),
      el('td', { class: 'total', text: comp.total ? String(comp.total) : '' }),
      data.profile ? el('td', { class: `need ${target ? target.status : ''}` },
        target ? [target.status[0].toUpperCase() + target.status.slice(1), el('small', { text: target.core ? 'core' : 'useful' })] : '') : null));
  }

  return [picker, score, el('div', { class: 'matrix-wrap' },
    el('table', { class: 'matrix' }, el('thead', {}, head), el('tbody', {}, body)))].filter(Boolean);
}

// -- drawer ----------------------------------------------------------------------

function openDrawer(...content) {
  drawer.replaceChildren(el('div', { class: 'drawer-inner' }, ...content));
  if (!drawer.open) drawer.showModal();
  drawer.scrollTop = 0;
}

function drawerHead(title, sub) {
  return el('div', { class: 'drawer-head' },
    el('div', { style: 'flex:1' }, el('h2', { id: 'drawer-title', text: title }), sub ? el('p', { class: 'sub', text: sub }) : null),
    el('button', { class: 'icon-button', type: 'button', 'aria-label': 'Close', onclick: () => drawer.close() },
      svg('svg', { viewBox: '0 0 20 20', 'aria-hidden': 'true' },
        svg('path', { d: 'M5 5l10 10M15 5L5 15', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round' }))));
}

drawer.addEventListener('click', (event) => { if (event.target === drawer) drawer.close(); });

function confirmButton(label, confirmLabel, action) {
  let armed = false;
  const button = el('button', { class: 'button danger', type: 'button' }, label);
  button.addEventListener('click', async () => {
    if (!armed) {
      armed = true;
      button.textContent = confirmLabel;
      button.classList.add('confirm');
      setTimeout(() => { armed = false; button.textContent = label; button.classList.remove('confirm'); }, 4000);
      return;
    }
    button.disabled = true;
    try { await action(); } catch (error) { toast(error.message, true); button.disabled = false; }
  });
  return button;
}

async function showEntry(id) {
  let entry;
  try { entry = await api(`/api/entries/${id}`); } catch (error) { return toast(error.message, true); }
  const where = entry.role ? `${entry.role.title}${entry.role.organisation ? ` at ${entry.role.organisation}` : ''}` : 'No role';
  const section = (heading, text, cls = '') => (text && text.trim()
    ? [el('h3', { text: heading }), el('p', { class: `text ${cls}`, text: text.trim() })] : []);

  openDrawer(
    drawerHead(entry.title, [entry.when, where].filter(Boolean).join(', ')),
    el('div', { class: 'drawer-body detail' },
      el('div', { class: 'row-meta' },
        entry.strength !== 2 ? el('span', { class: entry.strength === 3 ? 'headline-flag' : 'minor-flag', text: STRENGTHS[entry.strength] }) : null,
        entry.competency_names.map((n) => el('span', { class: 'chip', text: n })),
        entry.tags.map((t) => el('span', { class: 'chip tag', text: t }))),
      entry.summary ? el('p', { class: 'summary text', text: entry.summary }) : null,
      entry.missing.length ? el('p', { class: 'missing' },
        el('b', { text: 'Not interview-ready yet. ' }), `Add ${entry.missing.map((m) => STORY_LABELS[m]).join(', ')}.`) : null,
      section('Situation', entry.situation),
      section('Task', entry.task),
      section('What I did', entry.action),
      section('Result', entry.result),
      section('Impact', entry.impact),
      section('Still to confirm', entry.follow_ups, 'follow'),
      entry.raw.trim() ? el('details', {}, el('summary', {}, 'In your words'), el('p', { class: 'text', text: entry.raw.trim() })) : null),
    el('div', { class: 'drawer-foot' },
      el('button', { class: 'button primary', type: 'button', onclick: () => entryForm(entry) }, 'Edit'),
      confirmButton('Delete', 'Delete this entry?', async () => {
        await api(`/api/entries/${entry.id}`, { method: 'DELETE' });
        drawer.close();
        await reload();
        toast('Entry deleted');
      }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'ref', title: 'Use this number when asking Claude or Codex to change the entry', text: `Entry ${entry.id}` })));
}

function field(label, input, help) {
  return el('div', {}, el('label', { for: input.id }, label, help ? el('span', { class: 'help', text: ` ${help}` }) : null), input);
}

function entryForm(entry, defaults = {}) {
  const isNew = !entry;
  const e = entry || { title: '', summary: '', happened_from: '', happened_to: '', approximate: false, situation: '', task: '',
    action: '', result: '', impact: '', follow_ups: '', raw: '', strength: 2, competencies: [], tags: [], role_id: null, ...defaults };
  const text = (id, value, rows) => (rows
    ? el('textarea', { id: `f-${id}`, name: id, rows }, value || '')
    : el('input', { type: 'text', id: `f-${id}`, name: id, value: value || '' }));

  const roleSelect = el('select', { id: 'f-role', name: 'role' },
    isNew && !defaults.role_id ? el('option', { value: 'auto' }, 'Work it out from the date') : null,
    el('option', { value: '', selected: !isNew && !e.role_id }, 'No role'),
    [...meta.roles].reverse().map((r) => el('option', { value: r.id, selected: r.id === e.role_id },
      `${r.title}${r.organisation ? `, ${r.organisation}` : ''}`)));

  const areas = [...new Set(meta.competencies.map((c) => c.area))];
  const picker = el('fieldset', { class: 'comp-picker' }, el('legend', {}, 'Competencies this shows'),
    areas.map((area) => el('div', {},
      el('div', { class: 'area', text: area }),
      el('div', { class: 'opts' }, meta.competencies.filter((c) => c.area === area).map((c) =>
        el('label', { class: 'chip', title: c.description },
          el('input', { type: 'checkbox', name: 'competencies', value: c.slug, checked: e.competencies.includes(c.slug) }),
          c.name))))));

  const error = el('p', { class: 'form-error', role: 'alert' });
  const form = el('form', { class: 'drawer-body form', id: 'entry-form' },
    field('Title', text('title', e.title)),
    field('Summary', text('summary', e.summary, 3)),
    el('div', { class: 'pair' },
      field('From', text('happened_from', e.happened_from), 'e.g. 2019, 2019-06, 2021-Q3'),
      field('To', text('happened_to', e.happened_to), 'optional')),
    el('label', { class: 'check' }, el('input', { type: 'checkbox', name: 'approximate', checked: e.approximate }), 'Dates are approximate'),
    el('div', { class: 'pair' },
      field('Role', roleSelect),
      field('Strength', el('select', { id: 'f-strength', name: 'strength' },
        Object.entries(STRENGTHS).map(([v, label]) => el('option', { value: v, selected: Number(v) === e.strength }, label))))),
    picker,
    field('Tags', text('tags', e.tags.join(', ')), 'comma separated: projects, teams, tech'),
    field('Situation', text('situation', e.situation, 3)),
    field('Task', text('task', e.task, 2)),
    field('What I did', text('action', e.action, 4)),
    field('Result', text('result', e.result, 3)),
    field('Impact', text('impact', e.impact, 2), 'numbers and concrete outcomes'),
    field('Still to confirm', text('follow_ups', e.follow_ups, 2)),
    field('In your words', text('raw', e.raw, 4)),
    error);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const payload = {};
    for (const key of ['title', 'summary', 'happened_from', 'happened_to', 'situation', 'task', 'action', 'result', 'impact', 'follow_ups', 'raw']) {
      payload[key] = data.get(key);
    }
    payload.happened_from = payload.happened_from.trim() || null;
    payload.happened_to = payload.happened_to.trim() || null;
    payload.approximate = data.get('approximate') === 'on';
    payload.strength = Number(data.get('strength'));
    payload.competencies = data.getAll('competencies');
    payload.tags = data.get('tags').split(',').map((t) => t.trim()).filter(Boolean);
    const role = data.get('role');
    if (role !== 'auto') payload.role_id = role ? Number(role) : null;
    try {
      const saved = isNew
        ? await api('/api/entries', { method: 'POST', body: payload })
        : await api(`/api/entries/${e.id}`, { method: 'PATCH', body: payload });
      await reload();
      await showEntry(saved.id);
      toast(isNew ? 'Entry added' : 'Entry saved');
    } catch (err) {
      error.textContent = err.message;
    }
  });

  openDrawer(
    drawerHead(isNew ? 'Add entry' : 'Edit entry'),
    form,
    el('div', { class: 'drawer-foot' },
      el('button', { class: 'button primary', type: 'submit', form: 'entry-form' }, isNew ? 'Add entry' : 'Save'),
      el('button', { class: 'button', type: 'button', onclick: () => (isNew ? drawer.close() : showEntry(e.id)) }, 'Cancel')));
  form.querySelector('#f-title').focus();
}

function roleForm(role = null) {
  const isNew = !role;
  const r = role || { title: '', organisation: '', started: '', ended: '', summary: '' };
  const input = (id, value) => el('input', { type: 'text', id: `r-${id}`, name: id, value: value || '' });
  const error = el('p', { class: 'form-error', role: 'alert' });
  const form = el('form', { class: 'drawer-body form', id: 'role-form' },
    field('Title', input('title', r.title)),
    field('Organisation', input('organisation', r.organisation)),
    el('div', { class: 'pair' },
      field('Started', input('started', r.started), 'e.g. 2018-06'),
      field('Ended', input('ended', r.ended), 'leave empty if current')),
    field('Summary', el('textarea', { id: 'r-summary', name: 'summary', rows: 5 }, r.summary || '')),
    error);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(form));
    payload.ended = payload.ended.trim() || null;
    try {
      await (isNew ? api('/api/roles', { method: 'POST', body: payload }) : api(`/api/roles/${r.id}`, { method: 'PATCH', body: payload }));
      drawer.close();
      await reload();
      toast(isNew ? 'Role added' : 'Role saved');
    } catch (err) {
      error.textContent = err.message;
    }
  });

  openDrawer(
    drawerHead(isNew ? 'Add role' : 'Edit role'),
    form,
    el('div', { class: 'drawer-foot' },
      el('button', { class: 'button primary', type: 'submit', form: 'role-form' }, isNew ? 'Add role' : 'Save'),
      el('button', { class: 'button', type: 'button', onclick: () => drawer.close() }, 'Cancel'),
      el('span', { class: 'spacer' }),
      isNew ? null : confirmButton('Delete role', 'Delete? Entries stay', async () => {
        await api(`/api/roles/${r.id}`, { method: 'DELETE' });
        drawer.close();
        await reload();
        toast('Role deleted');
      })));
  form.querySelector('#r-title').focus();
}

// -- start -----------------------------------------------------------------------

async function reload() {
  await refresh();
  await render();
}

function setupTheme() {
  const root = document.documentElement;
  try {
    const saved = localStorage.getItem('receipts-theme');
    if (saved) root.dataset.theme = saved;
  } catch { /* storage unavailable */ }
  document.getElementById('theme').addEventListener('click', () => {
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('receipts-theme', root.dataset.theme); } catch { /* ignore */ }
  });
}

document.querySelector('[data-action="new-entry"]').addEventListener('click', () => entryForm());
window.addEventListener('hashchange', () => render().catch((error) => toast(error.message, true)));
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (route() === 'timeline') render(); }, 150);
});

setupTheme();
reload().catch((error) => {
  main.replaceChildren(el('div', { class: 'notice' },
    el('h1', { text: 'Could not load your record' }),
    el('p', { class: 'lede', text: `${error.message}. Check the terminal running Receipts, then reload this page.` })));
});
