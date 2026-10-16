'use strict';
(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pretty = value => String(value ?? '').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
  const statusLabel = status => ({completed_with_errors:'Completed with issues',retry_wait:'Retry scheduled',missing:'Missing',invalid:'Invalid input',blocked:'Needs attention'}[status] || pretty(status));
  const badge = status => `<span class="status status-${esc(status)}">${esc(statusLabel(status))}</span>`;
  const number = n => Number(n || 0).toLocaleString('en-US');
  const timestamp = s => new Date(/[Zz]|[+-]\d{2}:\d{2}$/.test(s) ? s : s + 'Z');
  const date = s => s ? timestamp(s).toLocaleString('en-GB', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
  let csrf = $('meta[name="csrf-token"]')?.content || '';
  let toastTimer;
  function toast(message, error = false) {
    const node = $('#toast'); node.textContent = message; node.classList.toggle('error', error); node.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => node.hidden = true, 6500);
  }
  async function api(path, options = {}) {
    const method = options.method || 'GET';
    const headers = {...options.headers};
    if (method !== 'GET' && path !== '/auth/login') {
      if (!csrf) { const session = await api('/session'); csrf = session.csrf_token; }
      headers['X-CSRF-Token'] = csrf;
    }
    if (options.body && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body);
    }
    let response;
    try { response = await fetch('/api/v1' + path, {...options, headers, credentials:'same-origin'}); }
    catch (_) { throw new Error('Could not reach the server. Check your connection and try again.'); }
    const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && document.body.dataset.page !== 'login') { window.location.assign('/'); }
      const detail = typeof data.detail === 'string' ? data.detail : null;
      const message = data.message || detail || (Array.isArray(data.detail) ? data.detail.map(x => x.msg).join('; ') : null) || `Request failed (${response.status}). Please try again.`;
      throw new Error(message + (data.request_id ? ` Reference: ${data.request_id}` : ''));
    }
    return data;
  }
  function showError(selector, error) { const el = $(selector); el.textContent = error.message || error; el.hidden = false; }
  async function busy(button, operation) {
    if (button.disabled) return;
    const original = button.innerHTML; button.disabled = true; button.textContent = 'Working…';
    try { return await operation(); } finally { button.disabled = false; button.innerHTML = original; }
  }
  function poll(callback, delay = 5000) {
    let running = false;
    const run = async () => { if (running || document.hidden) return; running = true; try { await callback(); } finally { running = false; } };
    run(); setInterval(run, delay);
  }
  const completed = task => ['succeeded','failed','invalid','missing'].reduce((sum, key) => sum + (task.counts?.[key] || 0), 0);
  const percent = task => task.total ? Math.min(100, Math.round(completed(task) / task.total * 100)) : 0;
  const sourceName = id => id === 'browser_demo' ? 'Browser calculator' : id === 'registry_demo' ? 'Registry API' : pretty(id);
  function dataSummary(data, empty = 'No result yet') {
    const fields = Object.entries(data || {});
    if (!fields.length) return `<span class="cell-secondary">${esc(empty)}</span>`;
    const priority = ['identifier', 'company_name', 'total'];
    fields.sort(([a], [b]) => (priority.includes(a) ? priority.indexOf(a) : 99) - (priority.includes(b) ? priority.indexOf(b) : 99));
    return `<dl class="data-summary">${fields.slice(0, 2).map(([key, value]) => `<div><dt>${esc(pretty(key))}</dt><dd>${esc(value ?? '—')}</dd></div>`).join('')}</dl>${fields.length > 2 ? `<span class="cell-secondary">+${fields.length - 2} more fields in details</span>` : ''}`;
  }

  document.querySelectorAll('[data-logout]').forEach(button => button.addEventListener('click', async event => {
    try { await busy(event.currentTarget, () => api('/auth/logout', {method:'POST'})); window.location.assign('/'); }
    catch (error) { toast(error.message, true); }
  }));
  const page = document.body.dataset.page;
  if (page === 'login') {
    $('#login-form').addEventListener('submit', async event => {
      event.preventDefault(); $('#login-error').hidden = true;
      try {
        await busy($('button[type=submit]', event.currentTarget), () => api('/auth/login', {method:'POST',body:{login:$('#login').value,password:$('#password').value}}));
        window.location.assign('/');
      } catch (error) { showError('#login-error', error); }
    });
  }
  if (page === 'dashboard') {
    let tasks = [], taskPage = 1, taskTotal = 0, loadRevision = 0, searchTimer;
    const initialFilters = new URLSearchParams(window.location.search);
    $('#task-search').value = initialFilters.get('q') || '';
    $('#task-status-filter').value = initialFilters.get('status') || '';
    function render() {
      const hasFilters = !!($('#task-search').value.trim() || $('#task-status-filter').value);
      const filtered = tasks;
      $('#task-count').textContent = number(taskTotal);
      $('#tasks-table-wrap').hidden = !filtered.length;
      $('#tasks-empty').hidden = taskTotal > 0 || hasFilters;
      $('#tasks-no-match').hidden = taskTotal > 0 || !hasFilters;
      $('#new-task-link').hidden = !taskTotal && !hasFilters;
      $('#tasks-loading').hidden = true;
      $('#tasks-body').innerHTML = filtered.map(task => `<tr><td class="task-name" data-label="Task"><a href="/tasks/${encodeURIComponent(task.id)}"><span class="task-file">▤</span><span>${esc(task.name)}<small class="cell-secondary">${number(task.total)} rows</small></span></a></td><td class="task-source" data-label="Source">${esc(sourceName(task.adapter))}</td><td class="task-status-cell" data-label="Status">${badge(task.status)}</td><td class="progress-cell" data-label="Processed"><span><span>${number(completed(task))} / ${number(task.total)}</span><span>${percent(task)}%</span></span><progress max="100" value="${percent(task)}" aria-label="Task progress"></progress></td><td class="task-created" data-label="Created">${esc(date(task.created_at))}</td><td class="task-open"><a class="arrow-link" aria-label="Open ${esc(task.name)}" href="/tasks/${encodeURIComponent(task.id)}">↗</a></td></tr>`).join('');
      $('#stat-total').textContent = number(taskTotal);
      $('#stat-active').textContent = number(tasks.filter(t => ['running','queued'].includes(t.status)).length);
      $('#stat-done').textContent = number(tasks.filter(t => ['completed','completed_with_errors'].includes(t.status)).length);
      $('#stat-attention').textContent = number(tasks.filter(t => ['paused','pause_requested','blocked','failed','completed_with_errors'].includes(t.status)).length);
      $('#tasks-pagination').hidden = taskTotal <= 50;
      $('#tasks-page-label').textContent = `${number((taskPage - 1) * 50 + 1)}–${number(Math.min(taskPage * 50, taskTotal))} of ${number(taskTotal)} tasks`;
      $('#tasks-prev').disabled = taskPage <= 1;
      $('#tasks-next').disabled = taskPage * 50 >= taskTotal;
    }
    function filtersChanged() {
      taskPage = 1;
      const params = new URLSearchParams();
      if ($('#task-search').value.trim()) params.set('q',$('#task-search').value.trim());
      if ($('#task-status-filter').value) params.set('status',$('#task-status-filter').value);
      history.replaceState(null,'',window.location.pathname + (params.size ? '?' + params.toString() : ''));
      loadTasks();
    }
    $('#task-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(filtersChanged,250); });
    $('#task-status-filter').addEventListener('change',filtersChanged);
    $('#clear-task-filters').addEventListener('click', () => { $('#task-search').value = ''; $('#task-status-filter').value = ''; filtersChanged(); $('#task-search').focus(); });
    async function loadTasks() {
      const revision = ++loadRevision;
      const params = new URLSearchParams({page:taskPage,page_size:50});
      if ($('#task-search').value.trim()) params.set('q',$('#task-search').value.trim());
      if ($('#task-status-filter').value) params.set('status',$('#task-status-filter').value);
      $('#tasks-table-wrap').setAttribute('aria-busy','true');
      try { const data = await api(`/tasks?${params}`); if (revision !== loadRevision) return; tasks = data.items; taskTotal = data.total; render(); }
      catch (error) { if (revision === loadRevision) { $('#tasks-loading').hidden = false; $('#tasks-loading').textContent = error.message; } }
      finally { if (revision === loadRevision) $('#tasks-table-wrap').setAttribute('aria-busy','false'); }
    }
    $('#tasks-prev').addEventListener('click', () => { if (taskPage > 1) { taskPage--; loadTasks(); } });
    $('#tasks-next').addEventListener('click', () => { if (taskPage * 50 < taskTotal) { taskPage++; loadTasks(); } });
    poll(loadTasks);
  }
  if (page === 'import') {
    let imported = null, sources = [], creating = false, uploading = false, sampleLoading = false, createdTask = null, currentStep = 1, reviewed = false;
    let selectedFile = null, importSignature = '', mappingBySource = {};
    const defaults = {quantity:'1',unit_price:'10',discount:'0'};
    const descriptions = {
      registry_demo:'Look up a company identifier and add company name, country, industry, employees, active status and risk score. Uses an included demo registry.',
      browser_demo:'Calculate an order in a browser using quantity, unit price and discount. Adds subtotal, discount amount, tax and total. Uses an included demo calculator.'
    };
    const outputFields = {
      registry_demo:['identifier','company_name','country','industry','employees','active','risk_score'],
      browser_demo:['identifier','quantity','unit_price','subtotal','discount_amount','tax','total']
    };
    function fields() { return sources.find(source => source.id === $('#adapter').value)?.fields || ['identifier']; }
    function mappedValues() {
      return Object.fromEntries([...document.querySelectorAll('.mapping-select')].filter(select => select.value).map(select => [select.name,select.value]));
    }
    function rememberMapping() { if ($('#mapping-fields').children.length) mappingBySource[$('#mapping-fields').dataset.source] = Object.fromEntries([...document.querySelectorAll('.mapping-select')].map(select => [select.name,select.value])); }
    function showStep(step, focus = true) {
      if (creating || createdTask || (step > 1 && !imported)) return;
      if (step === 3) { if (!$('#create-task-form').reportValidity()) return; reviewed = true; renderReview(); }
      currentStep = step;
      $('#upload-step').hidden = step !== 1; $('#configuration').hidden = step !== 2; $('#review-step').hidden = step !== 3;
      document.querySelectorAll('.wizard-steps li').forEach((node,index) => {
        if (index + 1 === step) node.setAttribute('aria-current','step'); else node.removeAttribute('aria-current');
        node.classList.toggle('step-done', index + 1 < step);
        $('button',node).disabled = index > 0 && (!imported || (index === 2 && !reviewed));
      });
      if (focus) { $([null,'#upload-heading','#mapping-heading','#review-heading'][step]).focus(); window.scrollTo({top:0,behavior:'instant'}); }
    }
    document.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => { rememberMapping(); showStep(Number(button.dataset.step)); }));
    function mapping() {
      rememberMapping();
      const adapter = $('#adapter').value, saved = mappingBySource[adapter] || {};
      $('#adapter-description').textContent = descriptions[adapter] || sources.find(source => source.id === adapter)?.description || '';
      $('#mapping-fields').dataset.source = adapter;
      $('#mapping-fields').innerHTML = fields().map(field => {
        const name = typeof field === 'string' ? field : field.name;
        const required = typeof field === 'object' ? !!field.required : name === 'identifier';
        const suggested = Object.hasOwn(saved,name) ? saved[name] : imported.headers.find(header => header.toLowerCase() === name.toLowerCase()) || '';
        const example = suggested ? imported.preview[0]?.[suggested] ?? 'Empty cell' : '';
        return `<div class="mapping-row"><label>${esc(pretty(name))} ${required ? '<span class="field-required">Required</span>' : '<span class="field-optional">Optional</span>'}<select name="${esc(name)}" class="mapping-select" ${required ? 'required' : ''} aria-describedby="mapping-help-${esc(name)}"><option value="">${required ? 'Choose a column' : `Use default: ${defaults[name] ?? 'empty'}`}</option>${imported.headers.map(header => `<option value="${esc(header)}" ${header === suggested ? 'selected' : ''}>${esc(header)}</option>`).join('')}</select></label><p class="field-help" id="mapping-help-${esc(name)}">${suggested ? `First row: ${esc(example)}` : required ? 'Choose the column containing each record’s identifier.' : `When not mapped, every row uses ${esc(defaults[name] ?? 'an empty value')}.`}</p></div>`;
      }).join('');
    }
    $('#mapping-fields').addEventListener('change', event => {
      const select = event.target.closest('select'); if (!select) return;
      $(`#mapping-help-${select.name}`).textContent = select.value ? `First row: ${imported.preview[0]?.[select.value] ?? 'Empty cell'}` : `When not mapped, every row uses ${defaults[select.name] ?? 'an empty value'}.`;
      rememberMapping(); reviewed = false;
    });
    async function loadSources() {
      if (sources.length) return;
      const data = await api('/sources'); sources = data.items;
      $('#adapter').innerHTML = sources.map(source => `<option value="${esc(source.id)}">${esc(sourceName(source.id))}</option>`).join('');
      if (!sources.length) throw new Error('No processing sources are available. Ask the administrator to configure a source.');
    }
    loadSources().catch(error => showError('#upload-error', error));
    $('#adapter').addEventListener('change', () => { mapping(); reviewed = false; });
    function changedFile(file) {
      selectedFile = file; imported = null; importSignature = ''; mappingBySource = {}; reviewed = false;
      $('#file-label').textContent = file?.name || 'Choose a file or drop it here';
      $('#sheet-field').hidden = true; $('#sheet-name').innerHTML = ''; showStep(1,false);
    }
    $('#file').addEventListener('change', () => changedFile($('#file').files[0]));
    const dropzone = $('#dropzone');
    ['dragenter','dragover'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.add('dragover'); }));
    ['dragleave','drop'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.remove('dragover'); }));
    dropzone.addEventListener('drop', event => {
      if (event.dataTransfer.files.length) { $('#file').files = event.dataTransfer.files; changedFile(event.dataTransfer.files[0]); }
    });
    async function upload() {
      if (uploading) return;
      $('#upload-error').hidden = true; $('#mapping-error').hidden = true;
      const file = selectedFile || $('#file').files[0];
      if (!file) return;
      const errorTarget = currentStep === 2 ? '#mapping-error' : '#upload-error';
      if (!/\.(csv|xlsx)$/i.test(file.name)) { showError(errorTarget, 'Choose a CSV or XLSX file.'); return; }
      if (file.size > 20 * 1024 * 1024) { showError(errorTarget, 'The file is larger than 20 MB. Choose a smaller file.'); return; }
      const signature = `${file.name}:${file.size}:${file.lastModified}:${$('#delimiter').value}:${$('#sheet-name').value}`;
      if (imported && signature === importSignature) { showStep(2); return; }
      uploading = true;
      try {
        await busy($('#preview-button'), async () => {
          await loadSources();
          const form = new FormData(); form.append('file',file); form.append('delimiter',$('#delimiter').value);
          if ($('#sheet-name').value) form.append('sheet_name',$('#sheet-name').value);
          imported = null; reviewed = false;
          const result = await api('/imports',{method:'POST',body:form});
          imported = result; selectedFile = file; reviewed = false;
          $('#preview-count').textContent = `${number(imported.row_count)} rows`;
          $('#preview-table').innerHTML = `<table><thead><tr>${imported.headers.map(header => `<th>${esc(header)}</th>`).join('')}</tr></thead><tbody>${imported.preview.map(row => `<tr>${imported.headers.map(header => `<td>${esc(row[header])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
          $('#sheet-field').hidden = imported.sheet_names.length < 2;
          $('#sheet-name').innerHTML = imported.sheet_names.map(sheet => `<option value="${esc(sheet)}" ${sheet === imported.sheet_name ? 'selected' : ''}>${esc(sheet)}</option>`).join('');
          importSignature = `${file.name}:${file.size}:${file.lastModified}:${$('#delimiter').value}:${$('#sheet-name').value}`;
          if (!$('#task-name').value) $('#task-name').value = file.name.replace(/\.[^.]+$/, '').replaceAll('_',' ').replaceAll('-',' ');
          mapping(); showStep(2);
        });
      } catch (error) { showError(errorTarget,error); $(errorTarget).focus(); }
      finally { uploading = false; }
    }
    $('#sheet-name').addEventListener('change', upload);
    $('#upload-form').addEventListener('submit', event => { event.preventDefault(); upload(); });
    document.querySelectorAll('[data-sample]').forEach(button => button.addEventListener('click', async () => {
      if (uploading || sampleLoading) return;
      sampleLoading = true;
      try {
        await busy(button,async () => {
          await loadSources();
          const response = await fetch(`/samples/${encodeURIComponent(button.dataset.sample)}?scenario=${encodeURIComponent(button.dataset.scenario)}`,{credentials:'same-origin'});
          if (!response.ok) throw new Error('Could not load the sample. Try again or upload your own file.');
          const file = new File([await response.blob()],button.dataset.scenario === 'issues' ? 'error-handling-sample.csv' : `${button.dataset.sample === 'registry_demo' ? 'company' : 'calculator'}-sample.csv`,{type:'text/csv'});
          const transfer = new DataTransfer(); transfer.items.add(file); $('#file').files = transfer.files;
          changedFile(file); $('#delimiter').value = ','; $('#adapter').value = button.dataset.sample; $('#task-name').value = file.name.replace('.csv','').replaceAll('-',' ');
          await upload();
        });
      } catch (error) { showError('#upload-error',error); }
      finally { sampleLoading = false; }
    }));
    function renderReview() {
      const adapter = $('#adapter').value, values = mappedValues();
      const section = (title,body,step) => `<section class="review-section"><div class="review-section-heading"><h3>${title}</h3>${step ? `<button type="button" class="text-button" data-review-edit="${step}" aria-label="Change ${title.toLowerCase()}">Change</button>` : ''}</div>${body}</section>`;
      const item = (key,value) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`;
      $('#review-summary').innerHTML = section('File',`<dl class="review-list">${item('File name',selectedFile.name)}${item('Rows',number(imported.row_count))}${imported.sheet_name ? item('Worksheet',imported.sheet_name) : ''}</dl>`,1) + section('Processing',`<dl class="review-list">${item('Task name',$('#task-name').value.trim())}${item('Source',sourceName(adapter))}</dl><p class="review-description">${esc(descriptions[adapter] || '')}</p>`,2) + section('Column mapping',`<dl class="review-list">${fields().map(field => { const key = typeof field === 'string' ? field : field.name; return item(pretty(key),values[key] ? `Column: ${values[key]}` : `Default: ${defaults[key] ?? 'empty'}`); }).join('')}</dl>`,2) + section('Your download',`<p class="review-description">CSV or XLSX with all ${number(imported.row_count)} original rows, your original columns, these result columns, and a status and error for each row.</p><div class="output-fields">${(outputFields[adapter] || []).map(key => `<span>${esc(pretty(key))}</span>`).join('')}</div>`,null);
      $('#launch-summary').textContent = `${number(imported.row_count)} rows · ${sourceName(adapter)}`;
      document.querySelectorAll('[data-review-edit]').forEach(button => button.addEventListener('click', () => showStep(Number(button.dataset.reviewEdit))));
    }
    $('#create-task-form').addEventListener('submit', event => { event.preventDefault(); if (!imported) return; rememberMapping(); reviewed = true; renderReview(); showStep(3); });
    $('#start-task').addEventListener('click', async () => {
      if (!imported || creating) return;
      creating = true; $('#create-error').hidden = true;
      document.querySelectorAll('[data-step],[data-review-edit]').forEach(button => button.disabled = true);
      try {
        await busy($('#start-task'), async () => {
          if (!createdTask) {
            createdTask = await api('/tasks',{method:'POST',body:{name:$('#task-name').value.trim(),import_id:imported.id,adapter:$('#adapter').value,mapping:mappedValues()}});
            sessionStorage.setItem('batchflow-saved-task',createdTask.id);
          }
          const latest = await api(`/tasks/${encodeURIComponent(createdTask.id)}`);
          if (latest.status === 'draft') await api(`/tasks/${encodeURIComponent(createdTask.id)}/start`,{method:'POST'});
          sessionStorage.removeItem('batchflow-saved-task');
          window.location.assign(`/tasks/${encodeURIComponent(createdTask.id)}`);
        });
      } catch (error) {
        showError('#create-error',createdTask ? `Task saved, but processing could not be confirmed. Retry start to continue this same task. ${error.message}` : error);
        $('#create-error').focus();
        if (createdTask) {
          $('#start-task').textContent = 'Retry start';
          $('#launch-summary').innerHTML = `<a class="text-link" href="/tasks/${encodeURIComponent(createdTask.id)}">Open saved task →</a>`;
        }
      } finally { creating = false; if (!createdTask) showStep(3,false); }
    });
    const savedTask = sessionStorage.getItem('batchflow-saved-task');
    if (savedTask) {
      $('#saved-task-notice').hidden = false;
      $('#saved-task-notice').innerHTML = `A task was saved during your last visit. <a class="text-link" href="/tasks/${encodeURIComponent(savedTask)}">Open the saved task</a> to check its progress before creating another.`;
    }
    if (new URLSearchParams(window.location.search).get('sample') === 'registry_demo') $('#try-sample').click();
  }
  if (page === 'task') {
    const id = encodeURIComponent(document.body.dataset.taskId);
    let task = null, rows = [], rowPage = 1, rowTotal = 0, refreshing = false, refreshRequested = false, mutating = false, detailBusy = false;
    const stateNotes = {
      draft:'This task is ready for validation. Start processing when you are ready.',
      queued:'Waiting for a worker to begin processing.',
      running:'Processing your rows. Results are saved after every row.',
      paused:'Processing is paused. Resume whenever you are ready.',
      pause_requested:'Pause requested. Rows already in progress are allowed to finish.',
      cancel_requested:'Cancellation requested. Rows already in progress may still finish.',
      cancelled:'This task was cancelled. Completed results remain available to export.',
      completed:'All rows have been processed. Your results are ready to export.',
      completed_with_errors:'Processing finished with issues. Review failed, invalid and missing rows before using the results.',
      blocked:'Processing needs attention. Check the reason below before resuming.',
      failed:'Processing stopped with an error. Review the details below.'
    };
    const notice = sessionStorage.getItem('batchflow-task-notice');
    if (notice) { showError('#task-error', notice); sessionStorage.removeItem('batchflow-task-notice'); }
    $('#export-csv').href = `/api/v1/tasks/${id}/export?format=csv`;
    $('#export-xlsx').href = `/api/v1/tasks/${id}/export?format=xlsx`;
    function renderTask() {
      $('#task-title').textContent = task.name;
      document.title = `${task.name} · Rowstead`;
      $('#task-meta').textContent = `${sourceName(task.adapter).toUpperCase()} · ${date(task.created_at)}`;
      const elapsed = task.started_at ? Math.max(1, ((task.finished_at ? timestamp(task.finished_at).getTime() : Date.now()) - timestamp(task.started_at).getTime()) / 1000) : 0;
      const rate = elapsed && completed(task) ? `${number(Math.round(completed(task) / elapsed * 60))} rows/min average since start` : 'Every result saved as it completes.';
      $('#task-subtitle').textContent = `${number(task.total)} rows · ${rate}`;
      $('#task-status').innerHTML = badge(task.status);
      $('#progress-number').textContent = `${percent(task)}%`;
      $('#processed-summary').textContent = `${number(completed(task))} of ${number(task.total)} rows processed`;
      $('#task-progressbar').setAttribute('aria-valuenow', percent(task));
      $('#task-progress').style.width = `${percent(task)}%`;
      $('#task-counters').innerHTML = ['succeeded','running','pending','retry_wait','failed','invalid','missing'].map(key => `<span><strong>${number(task.counts[key])}</strong>${esc(pretty(key))}</span>`).join('');
      $('#task-state-note').textContent = (stateNotes[task.status] || '') + (task.blocked_reason ? ` ${task.blocked_reason}` : '');
      const issueCount = ['failed','invalid','missing'].reduce((sum,key) => sum + (task.counts[key] || 0),0);
      $('#task-issues').hidden = !issueCount;
      $('#review-issues').textContent = `Review ${number(issueCount)} ${issueCount === 1 ? 'issue' : 'issues'} →`;
      $('#issues-description').textContent = [
        task.counts.failed ? `${number(task.counts.failed)} failed: processing could not finish after the allowed attempts. Retry failed rows when the source is available.` : '',
        task.counts.invalid ? `${number(task.counts.invalid)} invalid: correct the input in your spreadsheet and import it as a new task.` : '',
        task.counts.missing ? `${number(task.counts.missing)} missing: the source returned no matching record. Check the identifier before importing again.` : ''
      ].filter(Boolean).join(' ');
      let actions = [];
      if (task.status === 'draft') actions.push(['start','Start processing','primary']);
      if (['queued','running'].includes(task.status)) actions.push(['pause','Ⅱ Pause','secondary']);
      if (['paused','blocked'].includes(task.status)) actions.push(['resume','↻ Resume','primary']);
      if (['draft','queued','running','paused','pause_requested','blocked'].includes(task.status)) actions.push(['cancel','Cancel task','secondary']);
      if ((task.counts.failed || 0) > 0 && ['completed_with_errors','completed','failed'].includes(task.status)) actions.push(['retry-failed','↻ Retry failed rows','primary']);
      $('#task-actions').innerHTML = actions.map(([action,label,style]) => `<button class="button ${style}" data-action="${action}" ${mutating ? 'disabled' : ''}>${label}</button>`).join('');
    }
    function renderRows() {
      $('#row-count').textContent = number(rowTotal);
      $('#rows-empty').hidden = rows.length > 0;
      $('#rows-body').innerHTML = rows.map(row => `<tr><td class="row-number" data-label="Row">${number(row.row_number)}</td><td class="cell-data row-input" data-label="Input">${dataSummary(row.input_json, 'No input')}</td><td class="row-status" data-label="Status">${badge(row.status)}</td><td class="cell-data row-result ${row.error_message ? 'error' : ''}" data-label="Result / error">${row.error_message ? `<p class="row-error">${esc(row.error_message)}</p>` : dataSummary(row.output_json)}</td><td class="row-attempts" data-label="Attempts">${number(row.attempt_count)}<span class="mobile-only"> ${row.attempt_count === 1 ? 'attempt' : 'attempts'}</span></td><td class="row-action"><button class="button secondary small" data-row="${esc(row.id)}" aria-label="Details for row ${number(row.row_number)}">Details ↗</button></td></tr>`).join('');
      $('#page-label').textContent = rowTotal ? `${number((rowPage - 1) * 50 + 1)}–${number(Math.min(rowPage * 50, rowTotal))} of ${number(rowTotal)} rows` : '0 rows';
      $('#prev-page').disabled = rowPage <= 1; $('#next-page').disabled = rowPage * 50 >= rowTotal;
    }
    async function refresh() {
      if (refreshing || mutating) { refreshRequested = true; return; }
      refreshing = true;
      try {
        const rowParams = new URLSearchParams({page:rowPage,page_size:50});
        if ($('#row-filter').value === 'issues') rowParams.set('issues_only','true');
        else if ($('#row-filter').value) rowParams.set('status',$('#row-filter').value);
        const results = await Promise.all([api(`/tasks/${id}`), api(`/tasks/${id}/rows?${rowParams}`)]);
        task = results[0]; rows = results[1].items; rowTotal = results[1].total;
        renderTask(); renderRows();
      } catch (error) { showError('#task-error', error); }
      finally { refreshing = false; if (refreshRequested) { refreshRequested = false; refresh(); } }
    }
    async function action(name) {
      if (mutating) return;
      mutating = true; renderTask(); $('#task-error').hidden = true;
      try { task = await api(`/tasks/${id}/${name}`, {method:'POST'}); toast(name === 'retry-failed' ? 'Failed rows queued for another attempt.' : 'Task updated.'); }
      catch (error) { showError('#task-error', error); }
      finally { mutating = false; renderTask(); await refresh(); }
    }
    $('#task-actions').addEventListener('click', event => {
      const button = event.target.closest('[data-action]'); if (!button) return;
      if (button.dataset.action === 'cancel') $('#confirm-dialog').showModal(); else action(button.dataset.action);
    });
    $('#keep-task').addEventListener('click', () => $('#confirm-dialog').close());
    $('#confirm-cancel').addEventListener('click', () => { $('#confirm-dialog').close(); action('cancel'); });
    $('#row-filter').addEventListener('change', () => {
      rowPage = 1;
      $('#row-filter-help').textContent = $('#row-filter').value === 'issues' ? 'Showing failed, invalid and missing rows. Downloads still include all rows and their current statuses.' : 'Results appear as rows finish. Downloads always include every original row and its current status.';
      refresh();
    });
    $('#review-issues').addEventListener('click', () => {
      $('#row-filter').value = 'issues'; $('#row-filter').dispatchEvent(new Event('change'));
      $('#task-rows').scrollIntoView({behavior:'instant',block:'start'}); $('#row-filter').focus();
    });
    $('#prev-page').addEventListener('click', () => { if (rowPage > 1) { rowPage--; refresh(); } });
    $('#next-page').addEventListener('click', () => { if (rowPage * 50 < rowTotal) { rowPage++; refresh(); } });
    $('#close-row').addEventListener('click', () => $('#row-dialog').close());
    $('#rows-body').addEventListener('click', async event => {
      const button = event.target.closest('[data-row]'); if (!button || detailBusy) return;
      const row = rows.find(r => r.id === button.dataset.row); if (!row) return;
      detailBusy = true; $('#row-detail-title').textContent = `Row ${row.row_number}`;
      $('#row-detail-content').innerHTML = '<p class="muted">Loading attempt history…</p>'; $('#row-dialog').showModal();
      try {
        const data = await api(`/rows/${encodeURIComponent(row.id)}/attempts`);
        $('#row-detail-content').innerHTML = `${badge(row.status)}${['failed','invalid','missing'].includes(row.status) ? `<p class="row-status-explanation">${esc({failed:'Processing did not finish after the allowed attempts. Retry failed rows from the task when the source is available.',invalid:'The row contains invalid input. Correct it in the original spreadsheet and import a new task.',missing:'The source has no matching record. Check the identifier in the original spreadsheet.'}[row.status])}</p>` : ''}<h3>Original input</h3><pre>${esc(JSON.stringify(row.input_json, null, 2))}</pre><h3>Result</h3><pre>${esc(JSON.stringify(row.output_json, null, 2))}</pre>${row.error_message ? `<p class="inline-error">${esc(row.error_code)}: ${esc(row.error_message)}</p>` : ''}<h3>Attempt history</h3>${data.items.length ? data.items.map((attempt,index) => `<div class="attempt-item"><strong>Attempt ${index + 1}</strong> · ${esc(date(attempt.started_at))} · ${attempt.duration_ms == null ? 'In progress' : number(attempt.duration_ms) + ' ms'}<p>${esc(attempt.error_code ? `${pretty(attempt.error_code)}: ${attempt.redacted_message || 'No further details.'}` : attempt.finished_at ? 'Completed successfully.' : 'Execution in progress.')}</p></div>`).join('') : '<p class="muted">This row has not been attempted yet.</p>'}`;
      } catch (error) { $('#row-detail-content').textContent = error.message; }
      finally { detailBusy = false; }
    });
    poll(refresh);
  }
  if (page === 'sources') {
    api('/sources').then(data => {
      $('#source-list').innerHTML = data.items.length ? data.items.map(source => `<article class="panel source-card"><div class="source-card-top"><span class="source-icon">${source.id === 'browser_demo' ? '▣' : '⌘'}</span><span class="status status-completed">Configured</span></div><h2>${esc(source.name)}</h2><p>${esc(source.id === 'registry_demo' ? 'Look up company identifiers and add company information to your rows.' : 'Calculate order totals by entering each row into a browser form.')}</p><p class="source-scope">Included demo · no API key needed</p><div class="source-fields">INPUT FIELDS<br>${source.fields.map(field => `<span>${esc(typeof field === 'string' ? field : field.name)}</span>`).join('')}</div></article>`).join('') : '<div class="panel empty-state">No sources have been configured for this installation.</div>';
    }).catch(error => { $('#source-list').textContent = error.message; });
  }
})();
