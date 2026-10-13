(() => {
  'use strict';
  const root = document.documentElement;
  document.querySelectorAll('.theme-toggle').forEach(button => button.addEventListener('click', () => {
    const theme = root.dataset.bsTheme === 'dark' ? 'light' : 'dark';
    root.dataset.bsTheme = theme;
    try { localStorage.setItem('diary-theme', theme); } catch (_) {}
  }));
  const sidebar = document.getElementById('navigation');
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const mobile = window.matchMedia('(max-width: 991.98px)');
  function syncSidebar() {
    const open = mobile.matches ? root.classList.contains('sidebar-open') : !root.classList.contains('sidebar-collapsed');
    if (sidebarToggle) sidebarToggle.setAttribute('aria-expanded', String(open));
    if (sidebar) sidebar.inert = mobile.matches && !open;
    document.querySelectorAll('.sidebar-nav a').forEach(link => {
      const label = link.textContent.trim();
      link.setAttribute('aria-label', label);
      link.title = label;
    });
    if (sidebarToggle) sidebarToggle.setAttribute('aria-label', mobile.matches ? 'Toggle navigation' : open ? 'Minimise navigation' : 'Expand navigation');
  }
  function closeMobileSidebar() {
    root.classList.remove('sidebar-open'); syncSidebar();
    if (sidebarToggle) sidebarToggle.focus();
  }
  document.querySelectorAll('[data-sidebar-toggle]').forEach(button => button.addEventListener('click', () => {
    if (mobile.matches) {
      root.classList.toggle('sidebar-open');
      syncSidebar();
      if (root.classList.contains('sidebar-open')) sidebar.querySelector('a,button').focus();
      else sidebarToggle.focus();
    } else {
      root.classList.toggle('sidebar-collapsed');
      try { localStorage.setItem('diary-sidebar', root.classList.contains('sidebar-collapsed') ? 'collapsed' : 'open'); } catch (_) {}
      syncSidebar();
    }
  }));
  document.getElementById('sidebar-backdrop')?.addEventListener('click', closeMobileSidebar);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && root.classList.contains('sidebar-open')) closeMobileSidebar();
    if (event.key === 'Tab' && mobile.matches && root.classList.contains('sidebar-open')) {
      const focusable = Array.from(sidebar.querySelectorAll('a,button')).filter(el => !el.disabled);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  mobile.addEventListener('change', () => { root.classList.remove('sidebar-open'); syncSidebar(); });
  syncSidebar();

  function initForm(container) {
    const savedOffices = Array.from(container.querySelectorAll('#office-suggestions option')).map(option => option.value);
    container.querySelectorAll('.office-input').forEach(picker => {
      const input = picker.querySelector('input'), toggle = picker.querySelector('.office-toggle'), options = picker.querySelector('.office-options');
      // The visible picker supplements the native suggestions for keyboard/mobile use.
      function close() { options.hidden = true; toggle.setAttribute('aria-expanded', 'false'); }
      function show() {
        options.replaceChildren();
        const matches = savedOffices.filter(name => name.toLowerCase().includes(input.value.toLowerCase()));
        matches.forEach(name => {
          const button = document.createElement('button'); button.type = 'button'; button.textContent = name;
          button.addEventListener('click', () => { input.value = name; input.dispatchEvent(new Event('input', { bubbles: true })); close(); input.focus(); });
          options.append(button);
        });
        if (!matches.length) { const label = document.createElement('div'); label.className = 'office-empty'; label.textContent = savedOffices.length ? 'No matching offices.' : 'No saved offices.'; options.append(label); }
        options.hidden = false; toggle.setAttribute('aria-expanded', 'true');
      }
      toggle.addEventListener('click', () => options.hidden ? show() : close());
      input.addEventListener('input', () => { if (!options.hidden) show(); });
      picker.addEventListener('focusout', () => setTimeout(() => { if (!picker.contains(document.activeElement)) close(); }, 0));
      picker.addEventListener('keydown', event => { if (event.key === 'Escape' && !options.hidden) { event.stopPropagation(); close(); input.focus(); } if (event.key === 'ArrowDown') { event.preventDefault(); if (options.hidden) show(); options.querySelector('button')?.focus(); } });
    });
    const type = container.querySelector('#id_diary_type');
    const folders = container.querySelector('#id_no_of_folders');
    if (type && folders) {
      const update = () => {
        const letter = type.value === 'letter';
        folders.disabled = letter; folders.required = !letter; folders.min = letter ? '0' : '1';
        folders.closest('.field').classList.toggle('field-disabled', letter);
        if (letter) folders.value = '0';
      };
      type.addEventListener('change', update); update();
      ['id_received_from', 'id_marked_to'].forEach(id => container.querySelector('#' + id)?.setAttribute('list', 'office-suggestions'));
    }
    container.querySelectorAll('input[type=checkbox]').forEach(input => input.classList.add('form-check-input'));
  }
  initForm(document);
  const modalEl = document.getElementById('actionModal');
  const modalBody = document.getElementById('actionModalBody');
  let opener, loadController;
  if (modalEl) modalEl.addEventListener('hidden.bs.modal', () => {
    if (loadController) loadController.abort();
    modalBody.replaceChildren(); opener?.focus();
  });
  if (modalEl) modalEl.addEventListener('shown.bs.modal', () => modalBody.querySelector('input:not([type=hidden]):not(:disabled),select:not(:disabled),textarea:not(:disabled)')?.focus());
  document.addEventListener('click', async event => {
    const link = event.target.closest('[data-modal-url]');
    if (!link || !modalEl || !window.bootstrap || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); opener = link;
    if (mobile.matches && root.classList.contains('sidebar-open')) { root.classList.remove('sidebar-open'); syncSidebar(); }
    document.getElementById('actionModalTitle').textContent = link.dataset.modalTitle || link.textContent.trim();
    modalBody.innerHTML = '<div class="modal-loading"><span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Loading form…</div>';
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
    if (loadController) loadController.abort();
    loadController = new AbortController();
    try {
      const response = await fetch(link.dataset.modalUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, signal: loadController.signal });
      if (response.redirected) { window.location.assign(response.url); return; }
      if (!response.ok) throw new Error(response.status === 403 ? 'You do not have permission for this action.' : 'The form could not be loaded. Close this window and try again.');
      modalBody.innerHTML = await response.text(); initForm(modalBody);
      modalBody.querySelector('input:not([type=hidden]):not(:disabled),select:not(:disabled),textarea:not(:disabled)')?.focus();
    } catch (error) {
      if (error.name === 'AbortError') return;
      modalBody.replaceChildren(); const message = document.createElement('p'); message.className = 'modal-error'; message.textContent = error.message; modalBody.append(message);
    }
  });
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-modal-form]');
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector('[type=submit]');
    button.disabled = true; button.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      if (response.redirected) { window.location.assign(response.url); return; }
      if (response.status === 403) throw new Error('Your session or permission has changed. Refresh this page before saving.');
      if (response.status !== 422 && !response.ok) throw new Error('Unable to save. Your information is still here; please try again.');
      const result = await response.json();
      if (result.success) { window.location.reload(); return; }
      modalBody.innerHTML = result.html; initForm(modalBody);
      modalBody.querySelector('.has-errors input,.has-errors select,.has-errors textarea')?.focus();
    } catch (error) {
      const message = form.querySelector('.modal-request-error'); message.className = 'modal-request-error alert alert-danger'; message.textContent = error.message;
      button.disabled = false; button.removeAttribute('aria-busy');
    }
  });
  const filters = document.getElementById('diaryFilters');
  if (filters) {
    let timer, searchController;
    const status = document.getElementById('search-status');
    async function search() {
      if (!filters.reportValidity()) return;
      const url = new URL(window.location.href);
      for (const [key, value] of new FormData(filters)) { if (value) url.searchParams.set(key, value); else url.searchParams.delete(key); }
      url.searchParams.delete('page');
      if (searchController) searchController.abort();
      searchController = new AbortController(); status.textContent = 'Searching…';
      try {
        const response = await fetch(url, { signal: searchController.signal });
        if (response.redirected) { window.location.assign(response.url); return; }
        if (!response.ok) throw new Error('Check your filters and try again.');
        const page = new DOMParser().parseFromString(await response.text(), 'text/html');
        const results = page.getElementById('diary-list-results');
        if (!results) throw new Error('Unable to update results. Please refresh the page.');
        document.getElementById('diary-list-results').replaceWith(results);
        history.replaceState(null, '', url);
        document.querySelectorAll('details input[type=hidden]').forEach(input => input.value = url.searchParams.get(input.name) || '');
        status.textContent = 'Results updated.';
      } catch (error) { if (error.name !== 'AbortError') status.textContent = error.message; }
    }
    filters.querySelector('[name=q]').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 350); });
    filters.querySelectorAll('input:not([name=q]),select').forEach(input => input.addEventListener('change', () => {
      if (input.name === 'month' || input.name === 'year') ['date_from', 'date_to'].forEach(name => { const date = filters.querySelector('[name=' + name + ']'); if (date && date.type === 'hidden') date.value = ''; });
      search();
    }));
    filters.addEventListener('submit', event => { event.preventDefault(); clearTimeout(timer); search(); });
  }
})();
