const routes = (() => { try { return JSON.parse(document.documentElement.dataset.routes); } catch (e) { return {}; } })();

const state = {
  files: [],
  allFiles: [],
  trashFiles: [],
  folders: [],
  allFolders: [],
  trashFolders: [],
  currentFolderId: null,
  breadcrumb: [],
  summary: null,
  profile: null,
  currentView: 'files',
  category: 'all',
  search: '',
  sort: 'newest',
  viewMode: 'grid',
  loading: true,
  selection: new Set(),
  renameTarget: null,
  shareTarget: null,
  uploadQueue: [],
  contextTarget: null,
  currentPage: 1,
  pagination: null
};

document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  bootstrapWorkspace();
  setupNavigationGuards();
});

var _uploadInProgress = false;

function setupNavigationGuards() {
  window.addEventListener('popstate', function(e) {
    var params = new URLSearchParams(window.location.search);
    var fid = params.get('folder_id');
    state.currentFolderId = fid ? parseInt(fid) : null;
    state.currentPage = 1;
    if (state.currentView === 'files') {
      loadViewData(state.currentView);
    }
  });
  history.replaceState(null, '', location.pathname);

  window.addEventListener('beforeunload', function(e) {
    if (_uploadInProgress) {
      e.preventDefault();
      e.returnValue = '';
    }
  });
}

async function bootstrapWorkspace() {
  setLoading(true);
  clearBanner();

  const params = new URLSearchParams(window.location.search);
  const folderIdParam = params.get('folder_id');
  if (folderIdParam) {
    try { state.currentFolderId = parseInt(folderIdParam); } catch (e) { state.currentFolderId = null; }
  }

  try {
    const [profileResult, filesResult] = await Promise.all([
      fetchJSON(routes.profile),
      fetchJSON(routes.files + (folderIdParam ? '?folder_id=' + folderIdParam : ''))
    ]);
    state.profile = profileResult.user;
    state.allFiles = normalizeFiles(filesResult.files || []);
    state.files = state.allFiles;
    state.allFolders = filesResult.folders || [];
    state.folders = state.allFolders;
    state.summary = filesResult.summary || createEmptySummary();
    renderProfile();
    renderGreeting();
    renderStats();
    if (state.currentFolderId) {
      await loadBreadcrumb(state.currentFolderId);
    }
    renderWorkspace();
    renderFolderBar();
    promptForNameIfNeeded();
  } catch (error) {
    showBanner(error.message || 'Unable to load your workspace.', 'error');
    showToast(error.message || 'Workspace load failed', 'error');
    state.files = [];
    state.allFiles = [];
    state.summary = createEmptySummary();
    renderWorkspace();
  } finally {
    setLoading(false);
  }
}

function setupEventListeners() {
  let searchTimeout;
  document.getElementById('search-input').addEventListener('input', (e) => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      state.search = e.target.value.trim().toLowerCase();
      state.currentPage = 1;
      renderWorkspace();
    }, 300);
  });

  document.getElementById('sort-select').addEventListener('change', (e) => {
    state.sort = e.target.value;
    renderWorkspace();
  });

  document.querySelectorAll('.sidebar-nav .nav-item').forEach((btn) => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.view;
      if (!view) return;
      if (view === 'vault') {
        openVault();
        closeSidebar();
        return;
      }
      state.currentView = view;
      document.querySelectorAll('.sidebar-nav .nav-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      showMainViews();
      loadViewData(view);
      closeSidebar();
    });
  });

  document.querySelectorAll('.toggle-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.viewMode = btn.dataset.view;
      document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderWorkspace();
    });
  });

  document.getElementById('file-input').addEventListener('change', (e) => {
    handleUpload(Array.from(e.target.files || []));
  });

  document.getElementById('toolbar-upload-btn').addEventListener('click', openFilePicker);
  document.getElementById('refresh-btn').addEventListener('click', refreshFiles);
  document.getElementById('clear-search-btn').addEventListener('click', clearSearch);
  document.getElementById('bulk-delete-btn').addEventListener('click', bulkDeleteSelected);
  document.getElementById('bulk-favorite-btn').addEventListener('click', bulkFavoriteSelected);
  document.getElementById('clear-selection-btn').addEventListener('click', clearSelection);
  document.getElementById('rename-form').addEventListener('submit', submitRename);
  document.getElementById('name-form').addEventListener('submit', saveName);
  document.getElementById('edit-name-form').addEventListener('submit', saveEditName);
  document.getElementById('edit-profile-btn').addEventListener('click', openEditName);
  document.getElementById('share-form').addEventListener('submit', submitShare);
  document.getElementById('copy-share-btn').addEventListener('click', copyShareUrl);
  document.getElementById('mobile-menu-btn').addEventListener('click', toggleSidebar);
  document.getElementById('sidebar-close-btn').addEventListener('click', closeSidebar);
  document.getElementById('upload-panel-close').addEventListener('click', () => {
    document.getElementById('upload-panel').hidden = true;
  });

  document.querySelectorAll('[data-close-modal]').forEach((btn) => {
    btn.addEventListener('click', () => closeModal(btn.dataset.closeModal));
  });

  var moveModalClose = document.getElementById('move-modal-close');
  if (moveModalClose) moveModalClose.addEventListener('click', () => closeModal('modal-move'));
  var moveCancelBtn = document.getElementById('move-cancel-btn');
  if (moveCancelBtn) moveCancelBtn.addEventListener('click', () => closeModal('modal-move'));
  var moveConfirmBtn = document.getElementById('move-confirm-btn');
  if (moveConfirmBtn) moveConfirmBtn.addEventListener('click', () => confirmMoveFile());

  var newFolderBtn = document.getElementById('new-folder-btn');
  if (newFolderBtn) newFolderBtn.addEventListener('click', () => createNewFolder());

  var folderBackBtn = document.getElementById('folder-back-btn');
  if (folderBackBtn) folderBackBtn.addEventListener('click', () => navigateBack());
  var folderHomeBtn = document.getElementById('folder-home-btn');
  if (folderHomeBtn) folderHomeBtn.addEventListener('click', () => navigateHome());

  setupDropzone();
  setupContextMenu();
  setupKeyboardShortcuts();

  var overlay = document.getElementById('sidebar-overlay');
  if (overlay) overlay.addEventListener('click', closeSidebar);

  var logoutLink = document.getElementById('logout-link');
  if (logoutLink) {
    logoutLink.addEventListener('click', function(e) {
      e.preventDefault();
      showConfirm('Sign out?', 'You will be signed out of SkySync.', 'Sign out', false).then(function(ok) {
        if (ok) window.location.href = routes.logout;
      });
    });
  }
}

function setupDropzone() {
  var dropzone = document.getElementById('upload-dropzone');
  ['dragenter', 'dragover'].forEach(function(evt) {
    dropzone.addEventListener(evt, function(e) { e.preventDefault(); dropzone.classList.add('drag-over'); });
  });
  ['dragleave', 'drop'].forEach(function(evt) {
    dropzone.addEventListener(evt, function(e) { e.preventDefault(); dropzone.classList.remove('drag-over'); });
  });
  dropzone.addEventListener('drop', function(e) {
    handleUpload(Array.from(e.dataTransfer.files || []));
  });
  dropzone.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openFilePicker(); }
  });

  document.addEventListener('dragenter', function(e) { e.preventDefault(); document.body.classList.add('drag-active'); });
  document.addEventListener('dragleave', function(e) { if (e.relatedTarget === null) document.body.classList.remove('drag-active'); });
  document.addEventListener('drop', function(e) { document.body.classList.remove('drag-active'); });
}

function setupContextMenu() {
  const menu = document.getElementById('context-menu');
  document.addEventListener('click', () => { menu.hidden = true; });
  document.addEventListener('contextmenu', (e) => {
    const card = e.target.closest('.file-card');
    if (!card) return;
    e.preventDefault();
    const fileId = parseInt(card.dataset.fileId);
    const file = state.files.find(f => f.id === fileId);
    if (!file) return;
    state.contextTarget = file;

    const vaultMoveBtn = menu.querySelector('[data-action="vault-move"]');
    const vaultRestoreBtn = menu.querySelector('[data-action="vault-restore"]');
    if (file.is_vaulted) {
      vaultMoveBtn.hidden = true;
      vaultRestoreBtn.hidden = false;
    } else {
      vaultMoveBtn.hidden = false;
      vaultRestoreBtn.hidden = true;
    }

    menu.hidden = false;
    menu.style.left = `${Math.min(e.clientX, window.innerWidth - 200)}px`;
    menu.style.top = `${Math.min(e.clientY, window.innerHeight - 250)}px`;
  });

  menu.querySelectorAll('.ctx-item').forEach((item) => {
    item.addEventListener('click', () => {
      if (!state.contextTarget) return;
      handleFileAction(item.dataset.action, state.contextTarget);
      menu.hidden = true;
    });
  });
}

function setupKeyboardShortcuts() {
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      var confirmDialog = document.querySelector('.confirm-backdrop');
      if (confirmDialog) { confirmDialog.remove(); return; }
      closeModal('preview-modal');
      closeModal('rename-modal');
      closeModal('share-modal');
      closeModal('modal-move');
      closeModal('edit-name-modal');
      closeSidebar();
      clearSelection();
    }
    if (e.key === 'Delete' && state.selection.size > 0 && !document.querySelector('.confirm-backdrop')) {
      bulkDeleteSelected();
    }
    if (e.ctrlKey && e.key === 'a' && !e.target.matches('input,textarea,select')) {
      e.preventDefault();
      state.files.forEach(function(f) { state.selection.add(f.id); });
      renderWorkspace();
    }
  });
}

async function loadViewData(view) {
  setLoading(true);
  clearBanner();
  try {
    let url = routes.files;
    const params = [];
    if (view === 'trash') params.push('view=trash');
    else if (view === 'favorites') params.push('view=favorites');
    else if (state.currentFolderId) params.push('folder_id=' + state.currentFolderId);
    if (state.currentPage > 1) params.push('page=' + state.currentPage);
    if (params.length) url += '?' + params.join('&');

    const result = await fetchJSON(url);
    if (view === 'trash') {
      state.trashFiles = normalizeFiles(result.files || []);
      state.trashFolders = result.folders || [];
      state.files = state.trashFiles;
      state.folders = state.trashFolders;
    } else if (view === 'favorites') {
      state.files = normalizeFiles(result.files || []);
      state.folders = [];
    } else {
      state.allFiles = normalizeFiles(result.files || []);
      state.files = state.allFiles;
      state.allFolders = result.folders || [];
      state.folders = state.allFolders;
      state.summary = result.summary || createEmptySummary();
      renderStats();
    }
    state.pagination = result.pagination || null;
    state.selection.clear();
    renderWorkspace();
    renderFolderBar();
    if (state.currentFolderId && view === 'files') {
      loadBreadcrumb(state.currentFolderId);
    } else {
      state.breadcrumb = [];
      renderBreadcrumb();
    }
  } catch (error) {
    showBanner(error.message || 'Failed to load', 'error');
  } finally {
    setLoading(false);
  }
}

async function loadBreadcrumb(folderId) {
  try {
    const result = await fetchJSON('/api/folders/' + folderId + '/breadcrumb');
    state.breadcrumb = result.breadcrumb || [];
    renderBreadcrumb();
  } catch (e) {
    state.breadcrumb = [];
  }
}

function renderBreadcrumb() {
  const el = document.getElementById('breadcrumb');
  if (!el) return;
  if (!state.breadcrumb.length) {
    el.innerHTML = '';
    el.style.display = 'none';
    return;
  }
  el.style.display = 'flex';
  let html = '<span class="crumb" data-folder-id="__root__">My Drive</span>';
  state.breadcrumb.forEach((b, i) => {
    html += ' <span class="crumb-sep">/</span> ';
    if (i === state.breadcrumb.length - 1) {
      html += '<span class="crumb current">' + escapeHtml(b.name) + '</span>';
    } else {
      html += '<span class="crumb" data-folder-id="' + b.id + '">' + escapeHtml(b.name) + '</span>';
    }
  });
  el.innerHTML = html;
  el.querySelectorAll('.crumb[data-folder-id]').forEach(span => {
    span.addEventListener('click', function() {
      var fid = this.dataset.folderId;
      navigateFolder(fid === '__root__' ? null : parseInt(fid));
    });
  });
}

function navigateFolder(folderId) {
  state.currentFolderId = folderId;
  state.currentPage = 1;
  if (folderId) {
    history.pushState({ folderId: folderId }, '', '?folder_id=' + folderId);
  } else {
    history.pushState({ folderId: null }, '', location.pathname);
  }
  loadViewData(state.currentView);
}

function navigateBack() {
  history.back();
}

function navigateHome() {
  state.currentFolderId = null;
  state.currentPage = 1;
  history.pushState({ folderId: null }, '', location.pathname);
  loadViewData(state.currentView);
}

function renderFolderBar() {
  const bar = document.getElementById('folder-bar');
  if (!bar) return;
  const hint = document.getElementById('upload-hint');
  if (state.currentFolderId) {
    bar.style.display = 'flex';
    const folderName = state.breadcrumb.length ? state.breadcrumb[state.breadcrumb.length - 1].name : 'Folder';
    bar.querySelector('.folder-bar-title').textContent = 'Inside: ' + folderName;
    if (hint) {
      hint.hidden = false;
      hint.textContent = 'Uploading to: ' + folderName;
    }
  } else {
    bar.style.display = 'none';
    if (hint) {
      hint.hidden = true;
    }
  }
}

async function createNewFolder() {
  var name = await showPrompt('New folder', 'Enter a name for the new folder.', 'Folder name');
  if (!name || !name.trim()) return;
  try {
    await fetchJSON('/api/folders', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name.trim(), parent_id: state.currentFolderId})
    });
    showToast('Folder created', 'success');
    loadViewData(state.currentView);
  } catch (e) {
    showBanner(e.message || 'Failed to create folder', 'error');
  }
}

function showPrompt(title, message, placeholder) {
  return new Promise(function(resolve) {
    var backdrop = document.createElement('div');
    backdrop.className = 'confirm-backdrop';
    backdrop.setAttribute('role', 'dialog');
    backdrop.setAttribute('aria-modal', 'true');
    backdrop.setAttribute('aria-label', title);
    backdrop.innerHTML = '<div class="confirm-dialog"><h3>' + escapeHtml(title) + '</h3><p>' + escapeHtml(message) + '</p><input type="text" class="prompt-input" maxlength="200" placeholder="' + escapeHtml(placeholder) + '" aria-label="' + escapeHtml(placeholder) + '" style="width:100%;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);color:var(--text);border-radius:var(--radius-sm);padding:10px 14px;outline:none;margin-bottom:4px;font:inherit"><div class="confirm-actions"><button class="soft-btn" data-action="cancel">Cancel</button><button class="primary-btn" data-action="confirm">Create</button></div></div>';
    document.body.appendChild(backdrop);
    var input = backdrop.querySelector('.prompt-input');
    var confirmBtn = backdrop.querySelector('[data-action="confirm"]');
    var cancelBtn = backdrop.querySelector('[data-action="cancel"]');
    function cleanup(result) { backdrop.remove(); resolve(result); }
    input.focus();
    confirmBtn.addEventListener('click', function() { cleanup(input.value); });
    cancelBtn.addEventListener('click', function() { cleanup(null); });
    backdrop.addEventListener('click', function(e) { if (e.target === backdrop) cleanup(null); });
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); cleanup(input.value); }
      if (e.key === 'Escape') cleanup(null);
    });
  });
}

async function refreshFiles() {
  await loadViewData(state.currentView);
  showToast('Refreshed', 'success');
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || !data.success) {
    throw new Error(data.error?.message || data.error || 'Request failed');
  }
  return data;
}

function normalizeFiles(files) {
  return files.map(f => ({
    ...f,
    category: getCategoryFromType(f.type),
    uploadedDate: f.date ? new Date(f.date) : null
  }));
}

function renderGreeting() {
  const name = profileDisplayName(state.profile);
  const hour = new Date().getHours();
  let greeting = 'Good evening';
  if (hour < 12) greeting = 'Good morning';
  else if (hour < 17) greeting = 'Good afternoon';
  document.getElementById('greeting-text').textContent = name ? `${greeting}, ${name}` : greeting;
}

function renderProfile() {
  if (!state.profile) return;
  const displayName = profileDisplayName(state.profile) || 'SkySync Member';
  const metaLines = [];
  if (state.profile.phone) metaLines.push(formatPhoneNumber(state.profile.phone));
  if (state.profile.email && !state.profile.email.includes('telegram.local')) {
    metaLines.push(state.profile.email);
  }
  document.getElementById('profile-avatar').textContent = profileInitials(state.profile);
  document.getElementById('profile-name').textContent = displayName;
  document.getElementById('profile-meta').textContent = metaLines.join(' \u00B7 ') || 'Telegram account';
  document.getElementById('storage-target-chip').textContent = state.profile.storage_target || 'Telegram';
  document.getElementById('auth-mode-chip').textContent = state.profile.auth_mode === 'telegram' ? 'Telegram' : 'Local account';
  document.getElementById('hero-login-time').textContent = formatSessionTime(state.profile.login_time);
}

function renderStats() {
  const s = state.summary || createEmptySummary();
  document.getElementById('stat-total-files').textContent = s.total_files || 0;
  document.getElementById('stat-total-size').textContent = formatSize(s.total_size || 0);
  document.getElementById('stat-total-images').textContent = s.categories.images || 0;
  document.getElementById('stat-total-videos').textContent = s.categories.videos || 0;
  document.getElementById('stat-images').textContent = s.categories.images || 0;
  document.getElementById('stat-videos').textContent = s.categories.videos || 0;
  document.getElementById('stat-documents').textContent = s.categories.documents || 0;
  document.getElementById('stat-audio').textContent = s.categories.audio || 0;
  document.getElementById('storage-total').textContent = formatSize(s.total_size || 0);
  document.getElementById('storage-caption').textContent = s.total_files
    ? `${s.total_files} tracked file${s.total_files === 1 ? '' : 's'}`
    : 'No files uploaded yet';
  const usedPercent = Math.min(100, Math.round(((s.total_size || 0) / (10 * 1024 * 1024 * 1024)) * 100));
  document.getElementById('storage-meter').style.width = `${Math.max(3, usedPercent)}%`;

  document.getElementById('nav-count-all').textContent = state.allFiles.length;
  document.getElementById('nav-count-favorites').textContent = state.allFiles.filter(f => f.is_favorite).length;
  document.getElementById('nav-count-trash').textContent = state.trashFiles.length || 0;
}

function renderWorkspace() {
  renderSelectionBar();
  const filteredFiles = getFilteredFiles();
  const grid = document.getElementById('files-grid');
  const emptyState = document.getElementById('empty-state');
  const paginationEl = document.getElementById('pagination');
  const isTrash = state.currentView === 'trash';
  const isFavs = state.currentView === 'favorites';

  const titleMap = {
    files: 'All files',
    favorites: 'Favorites',
    recent: 'Recent files',
    trash: 'Trash'
  };
  let sectionTitle = titleMap[state.currentView] || 'All files';
  if (state.currentView === 'files' && state.currentFolderId) {
    const folder = state.breadcrumb.length ? state.breadcrumb[state.breadcrumb.length - 1] : null;
    sectionTitle = folder ? folder.name : 'Folder';
  }
  document.getElementById('section-title').textContent = sectionTitle;
  document.getElementById('section-subtitle').textContent = filteredFiles.length
    ? `${filteredFiles.length} item${filteredFiles.length === 1 ? '' : 's'}`
    : (state.search ? 'No matching files' : 'Nothing here yet');

  const emptyIcons = { files: '&#43;', favorites: '&#9733;', trash: '&#128465;', recent: '&#128337;' };
  const emptyTitles = {
    files: state.currentFolderId ? 'Folder is empty' : 'No files yet',
    favorites: 'No favorites yet',
    trash: 'Trash is empty',
    recent: 'No recent files'
  };
  const emptyMessages = {
    files: state.currentFolderId ? 'Upload files or create subfolders here.' : 'Upload your first file to get started.',
    favorites: 'Star your important files to find them quickly.',
    trash: 'Deleted files will appear here for 30 days.',
    recent: 'Files you upload will show up here.'
  };

  document.getElementById('empty-icon').innerHTML = emptyIcons[state.currentView] || '&#43;';
  document.getElementById('empty-title').textContent = emptyTitles[state.currentView] || 'Nothing here';
  document.getElementById('empty-message').textContent = emptyMessages[state.currentView] || '';

  var emptyActions = document.getElementById('empty-actions');
  if (emptyActions) {
    emptyActions.innerHTML = '';
    if (!isTrash && !isFavs && state.currentView !== 'recent') {
      var uploadBtn = document.createElement('button');
      uploadBtn.className = 'primary-btn';
      uploadBtn.textContent = 'Upload file';
      uploadBtn.addEventListener('click', openFilePicker);
      emptyActions.appendChild(uploadBtn);
      var folderBtn = document.createElement('button');
      folderBtn.className = 'soft-btn';
      folderBtn.textContent = '+ Folder';
      folderBtn.addEventListener('click', function() { createNewFolder(); });
      emptyActions.appendChild(folderBtn);
    }
  }

  grid.className = state.viewMode === 'list' ? 'files-grid list-view' : 'files-grid';
  grid.innerHTML = '';

  const hasFolders = state.folders && state.folders.length > 0;
  if (!filteredFiles.length && !hasFolders) {
    emptyState.hidden = false;
    paginationEl.hidden = true;
    return;
  }

  emptyState.hidden = true;
  const fragment = document.createDocumentFragment();

  if (hasFolders && !isTrash && !isFavs) {
    state.folders.forEach(folder => {
      const card = document.createElement('article');
      card.className = 'file-card folder-card';
      card.dataset.folderId = folder.id;
      const itemCount = folder.item_count || 0;
      const itemLabel = itemCount === 1 ? 'item' : 'items';
      card.innerHTML = `
        <div class="file-media folder-media">
          <div class="folder-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
        </div>
        <div class="file-info folder-info">
          <div class="file-name folder-name" title="${escapeHtml(folder.name)}">${escapeHtml(folder.name)}</div>
          <div class="file-meta folder-meta">${itemCount} ${itemLabel}</div>
        </div>
        <div class="file-actions folder-actions">
          <button class="soft-btn small folder-open-btn" type="button">Open</button>
          <button class="soft-btn small folder-delete-btn" type="button">Delete</button>
        </div>
      `;
      card.querySelector('.folder-open-btn').addEventListener('click', () => navigateFolder(folder.id));
      card.querySelector('.folder-delete-btn').addEventListener('click', () => deleteFolder(folder.id, folder.name));
      card.addEventListener('dblclick', () => navigateFolder(folder.id));
      fragment.appendChild(card);
    });
  }

  filteredFiles.forEach(file => {
    fragment.appendChild(renderFileCard(file, isTrash));
  });
  grid.appendChild(fragment);

  // Pagination
  if (state.pagination && state.pagination.total_pages > 1) {
    paginationEl.hidden = false;
    renderPagination(state.pagination);
  } else {
    paginationEl.hidden = true;
  }
}

function renderPagination(pag) {
  const el = document.getElementById('pagination');
  el.innerHTML = '';
  const prevBtn = document.createElement('button');
  prevBtn.disabled = pag.page <= 1;
  prevBtn.textContent = '« Prev';
  prevBtn.addEventListener('click', () => goToPage(pag.page - 1));
  el.appendChild(prevBtn);

  const maxShow = 5;
  let startPage = Math.max(1, pag.page - Math.floor(maxShow / 2));
  let endPage = Math.min(pag.total_pages, startPage + maxShow - 1);
  if (endPage - startPage < maxShow - 1) startPage = Math.max(1, endPage - maxShow + 1);
  for (let i = startPage; i <= endPage; i++) {
    const btn = document.createElement('button');
    btn.className = i === pag.page ? 'active' : '';
    btn.textContent = i;
    btn.addEventListener('click', () => goToPage(i));
    el.appendChild(btn);
  }

  const nextBtn = document.createElement('button');
  nextBtn.disabled = pag.page >= pag.total_pages;
  nextBtn.textContent = 'Next »';
  nextBtn.addEventListener('click', () => goToPage(pag.page + 1));
  el.appendChild(nextBtn);

  const info = document.createElement('span');
  info.className = 'pagination-info';
  info.textContent = `Page ${pag.page} of ${pag.total_pages} (${pag.total_files} files)`;
  el.appendChild(info);
}

async function goToPage(page) {
  if (!state.pagination || page < 1 || page > state.pagination.total_pages) return;
  state.currentPage = page;
  await loadViewData(state.currentView);
}

function renderFileCard(file, isTrash = false) {
  const article = document.createElement('article');
  article.className = `file-card ${state.viewMode === 'list' ? 'list-card' : ''} ${state.selection.has(file.id) ? 'selected' : ''}`;
  article.dataset.fileId = file.id;

  const favClass = file.is_favorite ? ' fav-star' : '';
  const media = file.type === 'image'
    ? `<img src="${previewUrl(file.id)}" alt="${escapeHtml(file.name)}" class="file-preview" loading="lazy" data-fallback="IMG">`
    : file.type === 'video'
      ? `<video src="${previewUrl(file.id)}" class="file-preview" muted playsinline preload="metadata"></video>`
      : file.type === 'audio'
        ? `<div class="file-glyph">AUD</div>`
        : `<div class="file-glyph">${fileGlyph(file.type)}</div>`;

  let actionsHtml = '';
  if (isTrash) {
    actionsHtml = `
      <button class="soft-btn small" type="button" data-action="restore">Restore</button>
      <button class="soft-btn small danger-btn" type="button" data-action="permanent-delete">Delete forever</button>
    `;
  } else {
    actionsHtml = `
      <button class="soft-btn small" type="button" data-action="preview">Preview</button>
      <button class="soft-btn small" type="button" data-action="download">Download</button>
      <button class="soft-btn small" type="button" data-action="rename">Rename</button>
      <button class="soft-btn small" type="button" data-action="share">Share</button>
      <button class="soft-btn small${favClass}" type="button" data-action="favorite">${file.is_favorite ? '&#9733;' : '&#9734;'} Fav</button>
      <button class="soft-btn small danger-btn" type="button" data-action="delete">Delete</button>
    `;
  }

  article.innerHTML = `
    <button class="select-pill ${state.selection.has(file.id) ? 'active' : ''}" type="button" aria-label="Select file">Select</button>
    <div class="file-media">${media}</div>
    <div class="file-body">
      <div class="file-topline">
        <div>
          <h3 title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</h3>
          <p>${formatTypeLabel(file.type)} \u00B7 ${formatSize(file.size || 0)}</p>
        </div>
        <span class="date-tag">${formatDate(file.date || file.deleted_at)}</span>
      </div>
      <div class="file-actions">${actionsHtml}</div>
    </div>
  `;

  article.querySelector('.select-pill').addEventListener('click', (e) => {
    e.stopPropagation();
    toggleSelection(file.id);
  });

  article.querySelectorAll('[data-action]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      handleFileAction(btn.dataset.action, file);
    });
  });

  article.addEventListener('dblclick', () => handleFileAction('preview', file));

  const previewImg = article.querySelector('img[data-fallback]');
  if (previewImg) {
    previewImg.addEventListener('error', function() {
      this.outerHTML = '<div class="file-glyph">IMG</div>';
    });
  }

  return article;
}

function handleFileAction(action, file) {
  switch (action) {
    case 'preview': openPreview(file); break;
    case 'download':
      showDownloadIndicator(file.name);
      var a = document.createElement('a');
      a.href = downloadUrl(file.id);
      a.download = file.name;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(hideDownloadIndicator, 5000);
      break;
    case 'rename':
      state.renameTarget = file;
      document.getElementById('rename-input').value = file.name;
      openModal('rename-modal');
      break;
    case 'delete': deleteSingleFile(file); break;
    case 'favorite': toggleFavorite(file); break;
    case 'share':
      state.shareTarget = file;
      document.getElementById('share-result').hidden = true;
      document.getElementById('share-url-input').value = '';
      openModal('share-modal');
      break;
    case 'restore': restoreSingleFile(file); break;
    case 'permanent-delete': permanentDeleteSingleFile(file); break;
    case 'move': openMoveModal(file); break;
    case 'vault-move': vaultMoveFile(file); break;
    case 'vault-restore': vaultRestoreFile(file); break;
  }
}

async function vaultMoveFile(file) {
  const ok = await showConfirm('Move to Vault?', `"${file.name}" will be hidden and protected.`, 'Move');
  if (!ok) return;
  try {
    await fetchJSON('/api/vault/move', { method: 'POST', body: JSON.stringify({ type: 'file', id: file.id }) });
    state.files = state.files.filter(f => f.id !== file.id);
    state.allFiles = state.allFiles.filter(f => f.id !== file.id);
    state.selection.delete(file.id);
    renderStats();
    renderWorkspace();
    showToast('File moved to vault', 'success');
  } catch (error) {
    showToast(error.message || 'Failed to move to vault', 'error');
  }
}

function openPreview(file) {
  const body = document.getElementById('preview-modal-body');
  const meta = `
    <div class="preview-meta">
      <h3>${escapeHtml(file.name)}</h3>
      <p>${formatTypeLabel(file.type)} \u00B7 ${formatSize(file.size || 0)} \u00B7 ${escapeHtml(file.mime_type || 'Unknown')}</p>
    </div>
  `;

  if (file.type === 'image') {
    body.innerHTML = `${meta}<img src="${previewUrl(file.id)}" alt="${escapeHtml(file.name)}" class="modal-media">`;
  } else if (file.type === 'video') {
    body.innerHTML = `${meta}<video src="${previewUrl(file.id)}" controls class="modal-media"></video>`;
  } else if (file.type === 'audio') {
    body.innerHTML = `${meta}<audio src="${previewUrl(file.id)}" controls style="width:100%;margin-top:12px;"></audio>`;
  } else {
    body.innerHTML = `
      ${meta}
      <div class="document-fallback">
        <div class="file-glyph large">${fileGlyph(file.type)}</div>
        <p>Preview is available for images, videos, and audio files.</p>
        <button class="primary-btn doc-download-btn">Download file</button>
      </div>
    `;
    body.querySelector('.doc-download-btn').addEventListener('click', () => { window.location.href = downloadUrl(file.id); });
  }
  openModal('preview-modal');
}

async function submitRename(event) {
  event.preventDefault();
  if (!state.renameTarget) return;
  const input = document.getElementById('rename-input');
  const name = input.value.trim();
  if (!name) { showToast('Enter a valid file name', 'error'); return; }

  try {
    const data = await fetchJSON(renameUrl(state.renameTarget.id), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    state.files = state.files.map(f => f.id === state.renameTarget.id ? { ...f, ...data.file, category: getCategoryFromType(data.file.type) } : f);
    state.allFiles = state.allFiles.map(f => f.id === state.renameTarget.id ? { ...f, ...data.file, category: getCategoryFromType(data.file.type) } : f);
    closeModal('rename-modal');
    state.renameTarget = null;
    renderWorkspace();
    showToast('File renamed', 'success');
  } catch (error) {
    showToast(error.message || 'Rename failed', 'error');
  }
}

async function toggleFavorite(file) {
  try {
    const data = await fetchJSON(`${routes.fileBase}${file.id}/favorite`, { method: 'POST' });
    const isFav = data.is_favorite;
    state.files = state.files.map(f => f.id === file.id ? { ...f, is_favorite: isFav } : f);
    state.allFiles = state.allFiles.map(f => f.id === file.id ? { ...f, is_favorite: isFav } : f);
    renderWorkspace();
    renderStats();
    showToast(isFav ? 'Added to favorites' : 'Removed from favorites', 'success');
  } catch (error) {
    showToast(error.message || 'Failed to update favorite', 'error');
  }
}

async function submitShare(event) {
  event.preventDefault();
  if (!state.shareTarget) return;
  const expiry = document.getElementById('share-expiry').value;
  const canDownload = document.getElementById('share-can-download').checked;

  try {
    const data = await fetchJSON(`${routes.fileBase}${state.shareTarget.id}/share`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        can_view: true,
        can_download: canDownload,
        expires_days: expiry ? parseInt(expiry) : null
      })
    });
    document.getElementById('share-url-input').value = data.share.url;
    document.getElementById('share-result').hidden = false;
    document.getElementById('create-share-btn').hidden = true;
    showToast('Share link created', 'success');
  } catch (error) {
    showToast(error.message || 'Failed to create share link', 'error');
  }
}

function copyShareUrl() {
  const input = document.getElementById('share-url-input');
  navigator.clipboard.writeText(input.value)
    .then(() => showToast('Link copied to clipboard', 'success'))
    .catch(() => { input.select(); document.execCommand('copy'); showToast('Link copied', 'success'); });
}

async function restoreSingleFile(file) {
  try {
    await fetchJSON(`${routes.fileBase}${file.id}/restore`, { method: 'POST' });
    state.trashFiles = state.trashFiles.filter(f => f.id !== file.id);
    state.files = state.trashFiles;
    state.selection.delete(file.id);
    renderStats();
    renderWorkspace();
    showToast('File restored', 'success');
  } catch (error) {
    showToast(error.message || 'Restore failed', 'error');
  }
}

async function permanentDeleteSingleFile(file) {
  const ok = await showConfirm('Delete permanently?', `"${file.name}" will be permanently deleted. This cannot be undone.`, 'Delete forever', true);
  if (!ok) return;
  try {
    await fetchJSON(`${routes.fileBase}${file.id}/permanent-delete`, { method: 'DELETE' });
    state.trashFiles = state.trashFiles.filter(f => f.id !== file.id);
    state.files = state.trashFiles;
    state.selection.delete(file.id);
    renderStats();
    renderWorkspace();
    showToast('File permanently deleted', 'success');
  } catch (error) {
    showToast(error.message || 'Delete failed', 'error');
  }
}

async function deleteSingleFile(file) {
  const ok = await showConfirm('Move to trash?', `"${file.name}" will be moved to Trash.`, 'Delete');
  if (!ok) return;
  try {
    await fetchJSON(`${routes.fileBase}${file.id}/delete`, { method: 'DELETE' });
    state.files = state.files.filter(f => f.id !== file.id);
    state.allFiles = state.allFiles.filter(f => f.id !== file.id);
    state.selection.delete(file.id);
    renderStats();
    renderWorkspace();
    showToast('File moved to trash', 'success');
  } catch (error) {
    showToast(error.message || 'Delete failed', 'error');
  }
}

async function deleteFolder(folderId, folderName) {
  const ok = await showConfirm('Delete folder?', `"${folderName}" and its contents will be moved to Trash.`, 'Delete');
  if (!ok) return;
  try {
    await fetchJSON('/api/folders/' + folderId + '/delete', { method: 'DELETE' });
    state.folders = state.folders.filter(f => f.id !== folderId);
    state.allFolders = state.allFolders.filter(f => f.id !== folderId);
    renderWorkspace();
    showToast('Folder moved to trash', 'success');
  } catch (error) {
    showToast(error.message || 'Delete failed', 'error');
  }
}

async function handleUpload(files) {
  if (!files.length) return;
  _uploadInProgress = true;
  var panel = document.getElementById('upload-panel');
  var list = document.getElementById('upload-list');
  panel.hidden = false;

  var uploadedCount = 0;
  for (var i = 0; i < files.length; i++) {
    var file = files[i];
    var itemId = 'upload-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
    var itemEl = document.createElement('div');
    itemEl.className = 'upload-item';
    itemEl.id = itemId;
    var glyphMap = { image: 'IMG', video: 'VID', document: 'DOC', audio: 'AUD' };
    var ext = file.name.split('.').pop().toUpperCase();
    var glyph = glyphMap[getCategoryFromType(file.type)] || ext.slice(0, 4);
    itemEl.innerHTML = '<div class="upload-item-header"><div class="upload-item-icon">' + escapeHtml(glyph) + '</div><div class="upload-item-info"><div class="upload-item-name">' + escapeHtml(file.name) + '</div><div class="upload-item-meta">' + formatSize(file.size) + '</div></div></div><div class="upload-progress"><div class="upload-progress-bar" style="width:0%"></div></div><div class="upload-item-status">Uploading...</div>';
    list.appendChild(itemEl);

    var bar = itemEl.querySelector('.upload-progress-bar');
    var statusEl = itemEl.querySelector('.upload-item-status');

    try {
      var result = await uploadSingleFile(file, bar, statusEl);
      if (result) uploadedCount++;
    } catch (error) {
      statusEl.textContent = '\u2717 ' + (error.message || 'Upload failed');
      statusEl.classList.add('error');
      showToast(error.message || 'Upload failed: ' + file.name, 'error');
    }
  }

  document.getElementById('file-input').value = '';
  await refreshFiles();
  _uploadInProgress = false;
  if (uploadedCount) {
    showToast(uploadedCount + ' file' + (uploadedCount === 1 ? '' : 's') + ' uploaded successfully', 'success');
  }
  setTimeout(function() { panel.hidden = true; list.innerHTML = ''; }, 4000);
}

function uploadSingleFile(file, bar, statusEl) {
  return new Promise(function(resolve, reject) {
    var xhr = new XMLHttpRequest();
    xhr.upload.addEventListener('progress', function(e) {
      if (e.lengthComputable) {
        var pct = Math.round((e.loaded / e.total) * 100);
        bar.style.width = pct + '%';
        statusEl.textContent = 'Uploading... ' + pct + '% (' + formatSize(e.loaded) + ' / ' + formatSize(e.total) + ')';
      }
    });
    xhr.addEventListener('load', function() {
      try {
        var data = JSON.parse(xhr.responseText);
        if (xhr.ok && data.success) {
          bar.style.width = '100%';
          statusEl.textContent = '\u2713 Uploaded successfully';
          statusEl.classList.add('success');
          resolve(true);
        } else {
          statusEl.textContent = '\u2717 ' + (data.error || 'Upload failed');
          statusEl.classList.add('error');
          resolve(false);
        }
      } catch (e) {
        statusEl.textContent = '\u2717 Upload failed';
        statusEl.classList.add('error');
        resolve(false);
      }
    });
    xhr.addEventListener('error', function() {
      statusEl.textContent = '\u2717 Network error';
      statusEl.classList.add('error');
      reject(new Error('Network error'));
    });
    var formData = new FormData();
    formData.append('file', file);
    if (state.currentFolderId) {
      formData.append('folder_id', state.currentFolderId);
    }
    xhr.open('POST', routes.upload);
    xhr.send(formData);
  });
}

async function bulkDeleteSelected() {
  const targets = state.files.filter(f => state.selection.has(f.id));
  if (!targets.length) return;
  const ok = await showConfirm('Delete selected files?', `${targets.length} file${targets.length === 1 ? '' : 's'} will be moved to Trash.`, 'Delete');
  if (!ok) return;

  try {
    await fetchJSON(`${routes.fileBase}bulk-delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_ids: targets.map(f => f.id) })
    });
    state.selection.clear();
    await refreshFiles();
    showToast('Files moved to trash', 'success');
  } catch (error) {
    showToast(error.message || 'Bulk delete failed', 'error');
  }
}

async function bulkFavoriteSelected() {
  const targets = state.files.filter(f => state.selection.has(f.id));
  if (!targets.length) return;

  for (const file of targets) {
    try {
      await fetchJSON(`${routes.fileBase}${file.id}/favorite`, { method: 'POST' });
    } catch (e) { /* skip */ }
  }
  state.selection.clear();
  await refreshFiles();
  showToast('Favorites updated', 'success');
}

function getFilteredFiles() {
  let files = [...state.files];

  if (state.search) {
    files = files.filter(f => {
      const haystack = `${f.name} ${f.type} ${f.mime_type || ''}`.toLowerCase();
      return haystack.includes(state.search);
    });
  }

  files.sort((a, b) => compareFiles(a, b, state.sort));
  return files;
}

function compareFiles(a, b, mode) {
  if (mode === 'name') return a.name.localeCompare(b.name);
  if (mode === 'size') return (b.size || 0) - (a.size || 0);
  const at = a.uploadedDate ? a.uploadedDate.getTime() : 0;
  const bt = b.uploadedDate ? b.uploadedDate.getTime() : 0;
  return mode === 'oldest' ? at - bt : bt - at;
}

function toggleSelection(fileId) {
  state.selection.has(fileId) ? state.selection.delete(fileId) : state.selection.add(fileId);
  renderWorkspace();
}

function clearSelection() {
  state.selection.clear();
  renderWorkspace();
}

function renderSelectionBar() {
  const strip = document.getElementById('selection-strip');
  const count = state.selection.size;
  strip.hidden = count === 0;
  document.getElementById('selection-count').textContent = count === 1 ? '1 selected' : `${count} selected`;
}

function setLoading(isLoading) {
  state.loading = isLoading;
  var loadingEl = document.getElementById('loading-state');
  var gridEl = document.getElementById('files-grid');
  if (isLoading) {
    loadingEl.style.display = 'none';
    gridEl.style.display = 'none';
    renderSkeletonGrid();
  } else {
    hideSkeletonGrid();
    loadingEl.style.display = 'none';
    gridEl.style.display = state.viewMode === 'list' ? 'flex' : 'grid';
  }
}

function showBanner(message, tone) {
  const banner = document.getElementById('inline-banner');
  banner.hidden = false;
  banner.className = `banner ${tone}`;
  banner.textContent = message;
}
function clearBanner() {
  const banner = document.getElementById('inline-banner');
  banner.hidden = true;
  banner.className = 'banner';
}

function showToast(message, tone = 'neutral') {
  const stack = document.getElementById('toast-stack');
  const toast = document.createElement('div');
  toast.className = `toast ${tone}`;
  toast.setAttribute('role', 'alert');
  const icons = { success: '\u2713', error: '\u2717', warning: '\u26A0', info: '\u2139' };
  toast.innerHTML = '<span class="toast-icon">' + (icons[tone] || '\u2139') + '</span><span class="toast-content">' + escapeHtml(String(message)) + '</span><button class="toast-close" aria-label="Dismiss">&times;</button>';
  toast.querySelector('.toast-close').addEventListener('click', function() { toast.remove(); });
  stack.appendChild(toast);
  setTimeout(function() { if (toast.parentNode) toast.remove(); }, 4000);
}

function openModal(id) {
  var el = document.getElementById(id);
  if (!el) return;
  el.hidden = false;
  var first = el.querySelector('input, button:not([data-close-modal]):not(.modal-close)');
  if (first) setTimeout(function() { first.focus(); }, 50);
}

function closeModal(id) {
  var el = document.getElementById(id);
  if (el) el.hidden = true;
}

function showConfirm(title, message, confirmText, isDanger) {
  return new Promise(function(resolve) {
    var backdrop = document.createElement('div');
    backdrop.className = 'confirm-backdrop';
    backdrop.setAttribute('role', 'dialog');
    backdrop.setAttribute('aria-modal', 'true');
    backdrop.setAttribute('aria-label', title);
    var confirmClass = isDanger ? 'danger-btn' : 'primary-btn';
    backdrop.innerHTML = '<div class="confirm-dialog"><h3>' + escapeHtml(title) + '</h3><p>' + escapeHtml(message) + '</p><div class="confirm-actions"><button class="soft-btn" data-action="cancel">Cancel</button><button class="' + confirmClass + '" data-action="confirm">' + escapeHtml(confirmText) + '</button></div></div>';
    document.body.appendChild(backdrop);
    var confirmBtn = backdrop.querySelector('[data-action="confirm"]');
    var cancelBtn = backdrop.querySelector('[data-action="cancel"]');
    function cleanup(result) {
      backdrop.remove();
      resolve(result);
    }
    confirmBtn.addEventListener('click', function() { cleanup(true); });
    cancelBtn.addEventListener('click', function() { cleanup(false); });
    backdrop.addEventListener('click', function(e) { if (e.target === backdrop) cleanup(false); });
    confirmBtn.focus();
    backdrop.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') cleanup(false);
      if (e.key === 'Enter') cleanup(true);
    });
  });
}

function openFilePicker() { document.getElementById('file-input').click(); }
function clearSearch() { state.search = ''; document.getElementById('search-input').value = ''; document.getElementById('search-input').focus(); renderWorkspace(); }
function toggleSidebar() {
  var sidebar = document.getElementById('sidebar');
  var overlay = document.getElementById('sidebar-overlay');
  var btn = document.getElementById('mobile-menu-btn');
  var isOpen = sidebar.classList.toggle('open');
  sidebar.setAttribute('aria-hidden', !isOpen);
  if (btn) btn.setAttribute('aria-expanded', isOpen);
  if (overlay) overlay.classList.toggle('active', isOpen);
  document.body.style.overflow = isOpen ? 'hidden' : '';
}
function closeSidebar() {
  var sidebar = document.getElementById('sidebar');
  var overlay = document.getElementById('sidebar-overlay');
  var btn = document.getElementById('mobile-menu-btn');
  sidebar.classList.remove('open');
  sidebar.setAttribute('aria-hidden', 'true');
  if (btn) btn.setAttribute('aria-expanded', 'false');
  if (overlay) overlay.classList.remove('active');
  document.body.style.overflow = '';
}

function renderSkeletonGrid() {
  var skel = document.getElementById('skeleton-grid');
  if (!skel) return;
  skel.innerHTML = '';
  skel.hidden = false;
  for (var i = 0; i < 8; i++) {
    var card = document.createElement('div');
    card.className = 'skeleton-card';
    card.innerHTML = '<div class="skeleton skeleton-media"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text-sm"></div>';
    skel.appendChild(card);
  }
  skel.style.display = 'grid';
  skel.style.gridTemplateColumns = 'repeat(auto-fill, minmax(250px, 1fr))';
  skel.style.gap = '16px';
}

function hideSkeletonGrid() {
  var skel = document.getElementById('skeleton-grid');
  if (skel) { skel.hidden = true; skel.innerHTML = ''; }
}

function showDownloadIndicator(filename) {
  var el = document.getElementById('download-indicator');
  var text = document.getElementById('download-indicator-text');
  if (el && text) {
    el.hidden = false;
    text.innerHTML = 'Downloading...<small>' + escapeHtml(filename) + '</small>';
  }
}

function hideDownloadIndicator() {
  var el = document.getElementById('download-indicator');
  if (el) el.hidden = true;
}

let moveTargetFile = null;
let moveSelectedFolderId = null;

function openMoveModal(file) {
  moveTargetFile = file;
  moveSelectedFolderId = file.folder_id || null;
  const list = document.getElementById('move-folder-list');
  const folders = (state.allFolders || []).filter(f => !f.is_deleted);
  let html = `<button class="move-folder-item ${moveSelectedFolderId === null ? 'active' : ''}" data-folder-id="null">&#127968; Root</button>`;
  folders.forEach(f => {
    const isActive = String(moveSelectedFolderId) === String(f.id);
    html += `<button class="move-folder-item ${isActive ? 'active' : ''}" data-folder-id="${f.id}">&#128193; ${escapeHtml(f.name)}</button>`;
  });
  list.innerHTML = html;
  list.querySelectorAll('.move-folder-item').forEach(btn => {
    btn.addEventListener('click', () => {
      list.querySelectorAll('.move-folder-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      moveSelectedFolderId = btn.dataset.folderId === 'null' ? null : parseInt(btn.dataset.folderId);
    });
  });
  openModal('modal-move');
}

async function confirmMoveFile() {
  if (!moveTargetFile) return;
  const folderId = moveSelectedFolderId;
  try {
    const r = await fetch(`/api/files/${moveTargetFile.id}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId })
    });
    const d = await r.json();
    if (r.ok) {
      showToast('File moved', 'success');
      closeModal('modal-move');
      await loadViewData(state.currentView);
    } else {
      showToast(d.error || 'Failed to move file', 'error');
    }
  } catch (e) {
    showToast('Network error', 'error');
  }
  moveTargetFile = null;
}

function promptForNameIfNeeded() {
  if (!state.profile || profileDisplayName(state.profile)) return;
  const input = document.getElementById('name-input');
  if (input) input.value = '';
  openModal('name-modal');
  if (input) setTimeout(() => input.focus(), 100);
}

async function saveName(event) {
  event.preventDefault();
  const input = document.getElementById('name-input');
  const btn = document.getElementById('name-save-btn');
  const name = (input?.value || '').trim();
  if (!name) { showToast('Please enter your name', 'error'); return; }
  if (btn) btn.disabled = true;
  try {
    const data = await fetchJSON(routes.profile, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    state.profile = data.user;
    renderProfile();
    renderGreeting();
    closeModal('name-modal');
    showToast(`Welcome, ${data.user.name}!`, 'success');
  } catch (error) {
    showToast(error.message || 'Could not save your name', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function openEditName() {
  if (!state.profile) return;
  document.getElementById('edit-name-input').value = state.profile.name || '';
  openModal('edit-name-modal');
}

async function saveEditName(event) {
  event.preventDefault();
  const input = document.getElementById('edit-name-input');
  const btn = document.getElementById('edit-name-save-btn');
  const name = (input?.value || '').trim();
  if (!name) { showToast('Please enter your name', 'error'); return; }
  if (btn) btn.disabled = true;
  try {
    const data = await fetchJSON(routes.profile, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    state.profile = data.user;
    renderProfile();
    renderGreeting();
    closeModal('edit-name-modal');
    showToast('Profile updated', 'success');
  } catch (error) {
    showToast(error.message || 'Could not update name', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function createEmptySummary() {
  return { total_files: 0, total_size: 0, categories: { images: 0, videos: 0, documents: 0, audio: 0, others: 0 } };
}

function getCategoryFromType(type) {
  const map = { image: 'images', video: 'videos', document: 'documents', audio: 'audio', others: 'others' };
  return map[type] || 'others';
}

function formatSize(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes, idx = 0;
  while (size >= 1024 && idx < units.length - 1) { size /= 1024; idx++; }
  return `${size.toFixed(size >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function formatDate(value) {
  if (!value) return '';
  const d = new Date(value);
  if (isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric' }).format(d);
}

function formatSessionTime(value) {
  if (!value) return 'Session active';
  const d = new Date(value);
  if (isNaN(d.getTime())) return 'Session active';
  return `Signed in ${new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(d)}`;
}

function formatTypeLabel(type) {
  return { image: 'Image', video: 'Video', document: 'Document', audio: 'Audio', others: 'File' }[type] || 'File';
}

function fileGlyph(type) {
  return { image: 'IMG', video: 'VID', document: 'DOC', audio: 'AUD', others: 'FILE' }[type] || 'FILE';
}

function previewUrl(id) { return `${routes.fileBase}${id}/preview`; }
function downloadUrl(id) { return `${routes.fileBase}${id}/download`; }
function renameUrl(id) { return `${routes.fileBase}${id}/rename`; }

function profileDisplayName(p) {
  const name = (p?.name || '').trim();
  if (name) return name;
  const email = p?.email || '';
  if (email) {
    const local = email.split('@')[0];
    return local && !local.startsWith('telegram_') ? local : '';
  }
  return '';
}

function profileInitials(p) {
  const name = profileDisplayName(p);
  if (name) {
    const parts = name.trim().split(/\s+/);
    return parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : name.slice(0, 2).toUpperCase();
  }
  return (p?.email || 'TD').slice(0, 2).toUpperCase();
}

function formatPhoneNumber(phone) {
  if (!phone) return '';
  const v = String(phone).trim();
  if (!v.startsWith('+')) return v;
  const digits = v.slice(1).replace(/\D/g, '');
  if (!digits) return v;
  if (digits.length === 12) return `+${digits.slice(0, 2)} ${digits.slice(2, 7)} ${digits.slice(7)}`;
  if (digits.length === 11) return `+${digits[0]} ${digits.slice(1, 4)} ${digits.slice(4, 7)} ${digits.slice(7)}`;
  return `+${digits.replace(/(\d{3})(?=\d)/g, '$1 ')}`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// WebDAV token management

function openWebDAVSettings() {
  openModal('webdav-modal');
  loadWebDAVTokens();
}

function loadWebDAVTokens() {
  const container = document.getElementById('webdav-token-list');
  if (!container) return;
  container.innerHTML = '<p>Loading tokens...</p>';
  fetchJSON('/api/webdav/tokens')
    .then(data => {
      if (!data.success) throw new Error(data.error || 'Failed to load tokens');
      if (data.tokens.length === 0) {
        container.innerHTML = '<p class="empty-text">No WebDAV tokens yet. Create one to get started.</p>';
        return;
      }
      container.innerHTML = data.tokens.map(token => `
        <div class="webdav-token-item">
          <div class="webdav-token-info">
            <span class="webdav-token-label">${escapeHtml(token.label)}</span>
            <span class="webdav-token-meta">Created: ${formatDate(token.created_at)}</span>
          </div>
          <div class="webdav-token-actions">
            <button class="soft-btn small" type="button" data-action="revoke" data-token-id="${token.id}" title="Revoke token">Revoke</button>
          </div>
        </div>
      `).join('');
      container.querySelectorAll('[data-action="revoke"]').forEach(btn => {
        btn.addEventListener('click', () => revokeWebDAVToken(btn.dataset.tokenId));
      });
    })
    .catch(err => {
      container.innerHTML = `<p class="error-text">${escapeHtml(err.message)}</p>`;
    });
}

function createWebDAVToken() {
  const labelInput = document.getElementById('webdav-token-label');
  const label = (labelInput.value || 'default').trim() || 'default';
  fetchJSON('/api/webdav/tokens', {
    method: 'POST',
    body: JSON.stringify({ label }),
    headers: { 'Content-Type': 'application/json' },
  }).then(data => {
    if (!data.success) throw new Error(data.error || 'Failed to create token');
    closeModal('webdav-create-modal');
    showWebDAVTokenCreated(data.token, label);
  }).catch(err => {
    showToast(err.message || 'Failed to create token', 'error');
  });
}

function showWebDAVTokenCreated(token, label) {
  const container = document.getElementById('webdav-token-list');
  if (!container) return;
  const user = state.profile || {};
  const webdavUrl = (user.webdav_url || (window.location.origin + '/webdav/'));
  container.innerHTML = `
    <div class="webdav-token-created">
      <div class="webdav-instructions">
        <h4>Connect with WebDAV</h4>
        <p><strong>Server:</strong> ${webdavUrl}</p>
        <p><strong>Username:</strong> Your user ID</p>
        <p><strong>Password (token):</strong> <code class="token-code">${escapeHtml(token)}</code></p>
        <p>Copy this token now — it will not be shown again.</p>
      </div>
    </div>
  `;
  loadWebDAVTokens();
}

function revokeWebDAVToken(tokenId) {
  showConfirm('Revoke WebDAV token?', 'This will immediately disable WebDAV access with this token.', 'Revoke')
    .then(confirmed => {
      if (!confirmed) return;
      fetchJSON(`/api/webdav/tokens/${tokenId}`, { method: 'DELETE' })
        .then(data => {
          if (!data.success) throw new Error(data.error || 'Failed to revoke token');
          showToast('Token revoked', 'success');
          loadWebDAVTokens();
        })
        .catch(err => showToast(err.message || 'Failed to revoke token', 'error'));
    });
}

// Event listeners
document.addEventListener('DOMContentLoaded', function() {
  const webdavBtn = document.getElementById('webdav-settings-btn');
  if (webdavBtn) {
    webdavBtn.addEventListener('click', openWebDAVSettings);
  }
  const createForm = document.getElementById('webdav-create-form');  if (createForm) {
    createForm.addEventListener('submit', function(e) {
      e.preventDefault();
      createWebDAVToken();
    });
  }
  const createBtn = document.getElementById('webdav-create-btn');
  if (createBtn) {
    createBtn.addEventListener('click', function(e) {
      e.preventDefault();
      openModal('webdav-create-modal');
    });
  }
});

/* ==========================================================================
   Smart Vault UI
   ========================================================================== */

const vaultState = {
  configured: false,
  unlocked: false,
  files: [],
  folders: [],
  breadcrumb: [],
  currentFolderId: null,
  autoLockTimer: null,
  autoLockSeconds: 300,
  autoLockRemaining: 300,
};

function setupVaultEventListeners() {
  var vaultNavBtn = document.getElementById('vault-nav-btn');
  if (vaultNavBtn) {
    vaultNavBtn.addEventListener('click', openVault);
  }

  var vaultPinForm = document.getElementById('vault-pin-form');
  if (vaultPinForm) {
    vaultPinForm.addEventListener('submit', function(e) {
      e.preventDefault();
      attemptVaultUnlock();
    });
  }

  var vaultLockBtn = document.getElementById('vault-lock-btn');
  if (vaultLockBtn) {
    vaultLockBtn.addEventListener('click', lockVaultConfirm);
  }

  var vaultUploadBtn = document.getElementById('vault-upload-btn');
  if (vaultUploadBtn) {
    vaultUploadBtn.addEventListener('click', function() {
      document.getElementById('vault-file-input').click();
    });
  }

  var vaultFileInput = document.getElementById('vault-file-input');
  if (vaultFileInput) {
    vaultFileInput.addEventListener('change', function(e) {
      handleVaultUpload(Array.from(e.target.files || []));
      e.target.value = '';
    });
  }

  var vaultNewFolderBtn = document.getElementById('vault-new-folder-btn');
  if (vaultNewFolderBtn) {
    vaultNewFolderBtn.addEventListener('click', createVaultFolder);
  }

  var vaultEmptyGoto = document.getElementById('vault-empty-goto-drive');
  if (vaultEmptyGoto) {
    vaultEmptyGoto.addEventListener('click', function() {
      navigateToFiles();
    });
  }
}

document.addEventListener('DOMContentLoaded', setupVaultEventListeners);

async function openVault() {
  if (state.currentView === 'vault') return;
  state.currentView = 'vault';
  vaultState.currentFolderId = null;
  document.querySelectorAll('.sidebar-nav .nav-item').forEach(function(b) { b.classList.remove('active'); });
  var vaultBtn = document.getElementById('vault-nav-btn');
  if (vaultBtn) vaultBtn.classList.add('active');

  hideAllViews();
  document.getElementById('vault-view').hidden = true;
  document.getElementById('vault-lock-screen').hidden = true;

  var status = await checkVaultStatus();
  if (!status.configured) {
    showVaultNotConfigured();
    return;
  }
  if (!status.unlocked) {
    showVaultLockScreen();
    return;
  }
  vaultState.configured = true;
  vaultState.unlocked = true;
  showVaultUnlocked();
  await loadVaultData();
}

async function checkVaultStatus() {
  try {
    var data = await fetchJSON('/api/vault/status');
    vaultState.configured = data.configured;
    vaultState.unlocked = data.unlocked;
    updateVaultNav();
    return data;
  } catch (e) {
    return { configured: false, unlocked: false };
  }
}

function updateVaultNav() {
  var icon = document.getElementById('vault-nav-icon');
  var subtitle = document.getElementById('vault-nav-subtitle');
  var btn = document.getElementById('vault-nav-btn');
  if (!icon || !subtitle || !btn) return;

  if (vaultState.unlocked) {
    icon.innerHTML = '&#128275;';
    subtitle.textContent = vaultState.files.length + ' items';
    btn.classList.add('vault-unlocked');
  } else {
    icon.innerHTML = '&#128274;';
    subtitle.textContent = vaultState.configured ? 'Locked' : 'Not set up';
    btn.classList.remove('vault-unlocked');
  }
}

function hideAllViews() {
  var mainPanel = document.querySelector('.main-panel');
  if (mainPanel) {
    var sections = mainPanel.querySelectorAll('.stats-row, .toolbar.panel, .content-panel, .status-strip');
    sections.forEach(function(s) { s.hidden = true; });
    var header = mainPanel.querySelector('.dashboard-header');
    if (header) header.hidden = true;
  }
}

function showMainViews() {
  var mainPanel = document.querySelector('.main-panel');
  if (mainPanel) {
    var sections = mainPanel.querySelectorAll('.stats-row, .toolbar.panel, .content-panel, .status-strip');
    sections.forEach(function(s) { s.hidden = false; });
    var header = mainPanel.querySelector('.dashboard-header');
    if (header) header.hidden = false;
  }
  document.getElementById('vault-view').hidden = true;
  document.getElementById('vault-lock-screen').hidden = true;
}

function showVaultLockScreen() {
  document.getElementById('vault-view').hidden = true;
  var lockScreen = document.getElementById('vault-lock-screen');
  lockScreen.hidden = false;
  var pinInput = document.getElementById('vault-pin-input');
  if (pinInput) {
    pinInput.value = '';
    pinInput.focus();
  }
  var errorEl = document.getElementById('vault-pin-error');
  if (errorEl) errorEl.hidden = true;
}

function showVaultUnlocked() {
  document.getElementById('vault-lock-screen').hidden = true;
  document.getElementById('vault-view').hidden = false;
  startAutoLockTimer();
}

function showVaultNotConfigured() {
  document.getElementById('vault-view').hidden = true;
  var lockScreen = document.getElementById('vault-lock-screen');
  lockScreen.hidden = false;
  var card = lockScreen.querySelector('.vault-lock-card');
  if (card) {
    card.innerHTML = '<div class="vault-lock-icon">&#128274;</div>' +
      '<h2 class="vault-lock-title">Vault Not Set Up</h2>' +
      '<p class="vault-lock-desc">Go to Settings to set up your Vault PIN.</p>';
  }
}

async function attemptVaultUnlock() {
  var pinInput = document.getElementById('vault-pin-input');
  var errorEl = document.getElementById('vault-pin-error');
  var unlockBtn = document.getElementById('vault-unlock-btn');

  var pin = pinInput.value;
  if (!pin) {
    errorEl.hidden = false;
    return;
  }

  unlockBtn.disabled = true;
  unlockBtn.textContent = 'Unlocking...';
  errorEl.hidden = true;

  try {
    var data = await fetchJSON('/api/vault/unlock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: pin })
    });
    if (data.success) {
      vaultState.unlocked = true;
      vaultState.configured = true;
      updateVaultNav();
      showVaultUnlocked();
      await loadVaultData();
    } else {
      errorEl.textContent = 'Invalid Vault PIN';
      errorEl.hidden = false;
      pinInput.value = '';
      pinInput.focus();
    }
  } catch (e) {
    errorEl.textContent = 'Invalid Vault PIN';
    errorEl.hidden = false;
    pinInput.value = '';
    pinInput.focus();
  } finally {
    unlockBtn.disabled = false;
    unlockBtn.textContent = 'Unlock';
  }
}

async function loadVaultData() {
  try {
    var url = '/api/files?view=vault';
    if (vaultState.currentFolderId) {
      url += '&folder_id=' + vaultState.currentFolderId;
    }
    var result = await fetchJSON(url);
    vaultState.files = normalizeFiles(result.files || []);
    vaultState.folders = result.folders || [];
    updateVaultNav();
    renderVaultView();
    if (vaultState.currentFolderId) {
      await loadVaultBreadcrumb(vaultState.currentFolderId);
    } else {
      vaultState.breadcrumb = [];
      renderVaultBreadcrumb();
    }
  } catch (e) {
    if (e.message && e.message.toLowerCase().includes('vault')) {
      forceVaultLock();
    }
  }
}

function renderVaultView() {
  var grid = document.getElementById('vault-files-grid');
  var emptyState = document.getElementById('vault-empty-state');
  var subtitle = document.getElementById('vault-header-subtitle');
  var titleEl = document.getElementById('vault-section-title');
  var subEl = document.getElementById('vault-section-subtitle');

  var totalItems = vaultState.files.length + vaultState.folders.length;
  if (subtitle) subtitle.textContent = totalItems + ' item' + (totalItems === 1 ? '' : 's');
  if (titleEl) titleEl.textContent = 'Vault';
  if (subEl) subEl.textContent = totalItems + ' item' + (totalItems === 1 ? '' : 's');

  grid.innerHTML = '';

  if (totalItems === 0) {
    emptyState.hidden = false;
    grid.hidden = true;
    return;
  }

  emptyState.hidden = true;
  grid.hidden = false;
  var fragment = document.createDocumentFragment();

  vaultState.folders.forEach(function(folder) {
    var card = document.createElement('article');
    card.className = 'file-card folder-card';
    card.dataset.folderId = folder.id;
    var itemCount = folder.item_count || 0;
    var itemLabel = itemCount === 1 ? 'item' : 'items';
    card.innerHTML =
      '<div class="file-media folder-media">' +
        '<div class="folder-icon">' +
          '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>' +
          '</svg>' +
        '</div>' +
      '</div>' +
      '<div class="file-info folder-info">' +
        '<div class="file-name folder-name" title="' + escapeHtml(folder.name) + '">' + escapeHtml(folder.name) + '</div>' +
        '<div class="file-meta folder-meta">' + itemCount + ' ' + itemLabel + '</div>' +
      '</div>' +
      '<div class="file-actions folder-actions">' +
        '<button class="soft-btn small folder-open-btn" type="button">Open</button>' +
        '<button class="soft-btn small vault-restore-folder-btn" type="button">Restore</button>' +
      '</div>';
    card.querySelector('.folder-open-btn').addEventListener('click', function() { navigateVaultFolder(folder.id); });
    card.querySelector('.vault-restore-folder-btn').addEventListener('click', function() { vaultRestoreFolder(folder.id, folder.name); });
    card.addEventListener('dblclick', function() { navigateVaultFolder(folder.id); });
    fragment.appendChild(card);
  });

  vaultState.files.forEach(function(file) {
    fragment.appendChild(renderVaultFileCard(file));
  });

  grid.appendChild(fragment);
}

function renderVaultFileCard(file) {
  var article = document.createElement('article');
  article.className = 'file-card';
  article.dataset.fileId = file.id;

  var glyph = fileGlyph(file.category);
  var isImage = file.type === 'image';
  var isVideo = file.type === 'video';
  var isAudio = file.type === 'audio';

  var mediaContent = '';
  if (isImage) {
    mediaContent = '<img src="' + previewUrl(file.id) + '" alt="' + escapeHtml(file.name) + '" class="file-thumb" loading="lazy">';
  } else if (isVideo) {
    mediaContent = '<div class="file-glyph">' + glyph + '</div>';
  } else {
    mediaContent = '<div class="file-glyph">' + glyph + '</div>';
  }

  article.innerHTML =
    '<div class="file-media">' + mediaContent + '</div>' +
    '<div class="file-info">' +
      '<div class="file-name" title="' + escapeHtml(file.name) + '">' + escapeHtml(file.name) + '</div>' +
      '<div class="file-meta">' + formatSize(file.size || 0) + ' &middot; ' + formatDate(file.date) + '</div>' +
    '</div>' +
    '<div class="file-actions">' +
      '<button class="soft-btn small" type="button" data-action="preview" title="Preview">&#128269;</button>' +
      '<button class="soft-btn small" type="button" data-action="download" title="Download">&#11015;</button>' +
      '<button class="soft-btn small" type="button" data-action="vault-restore" title="Restore to My Drive">&#128275;</button>' +
    '</div>';

  article.querySelector('[data-action="preview"]').addEventListener('click', function() { openPreview(file); });
  article.querySelector('[data-action="download"]').addEventListener('click', function() {
    showDownloadIndicator(file.name);
    var a = document.createElement('a');
    a.href = downloadUrl(file.id);
    a.download = file.name;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(hideDownloadIndicator, 5000);
  });
  article.querySelector('[data-action="vault-restore"]').addEventListener('click', function() { vaultRestoreFile(file); });

  return article;
}

function navigateVaultFolder(folderId) {
  vaultState.currentFolderId = folderId;
  history.pushState({ vaultFolderId: folderId }, '', '?vault_folder=' + folderId);
  loadVaultData();
}

async function loadVaultBreadcrumb(folderId) {
  try {
    var result = await fetchJSON('/api/folders/' + folderId + '/breadcrumb');
    vaultState.breadcrumb = result.breadcrumb || [];
    renderVaultBreadcrumb();
  } catch (e) {
    vaultState.breadcrumb = [];
    renderVaultBreadcrumb();
  }
}

function renderVaultBreadcrumb() {
  var el = document.getElementById('vault-breadcrumb');
  if (!el) return;
  if (!vaultState.breadcrumb.length && !vaultState.currentFolderId) {
    el.innerHTML = '';
    el.style.display = 'none';
    return;
  }
  el.style.display = 'flex';
  var html = '<span class="crumb" data-vault-folder="__root__">Vault</span>';
  vaultState.breadcrumb.forEach(function(b, i) {
    html += ' <span class="crumb-sep">/</span> ';
    if (i === vaultState.breadcrumb.length - 1) {
      html += '<span class="crumb current">' + escapeHtml(b.name) + '</span>';
    } else {
      html += '<span class="crumb" data-vault-folder="' + b.id + '">' + escapeHtml(b.name) + '</span>';
    }
  });
  el.innerHTML = html;
  el.querySelectorAll('.crumb[data-vault-folder]').forEach(function(span) {
    span.addEventListener('click', function() {
      var fid = this.dataset.vaultFolder;
      vaultNavigateBreadcrumb(fid === '__root__' ? null : parseInt(fid));
    });
  });
}

function vaultNavigateBreadcrumb(folderId) {
  vaultState.currentFolderId = folderId;
  if (folderId) {
    history.pushState({ vaultFolderId: folderId }, '', '?vault_folder=' + folderId);
  } else {
    history.pushState({ vaultFolderId: null }, '', location.pathname);
  }
  loadVaultData();
}

async function attemptVaultUnlock() {
  var pinInput = document.getElementById('vault-pin-input');
  var errorEl = document.getElementById('vault-pin-error');
  var unlockBtn = document.getElementById('vault-unlock-btn');

  var pin = pinInput.value;
  if (!pin) {
    errorEl.hidden = false;
    return;
  }

  unlockBtn.disabled = true;
  unlockBtn.textContent = 'Unlocking...';
  errorEl.hidden = true;

  try {
    var data = await fetchJSON('/api/vault/unlock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: pin })
    });
    if (data.success) {
      vaultState.unlocked = true;
      vaultState.configured = true;
      updateVaultNav();
      showVaultUnlocked();
      await loadVaultData();
    } else {
      errorEl.textContent = 'Invalid Vault PIN';
      errorEl.hidden = false;
      pinInput.value = '';
      pinInput.focus();
    }
  } catch (e) {
    errorEl.textContent = 'Invalid Vault PIN';
    errorEl.hidden = false;
    pinInput.value = '';
    pinInput.focus();
  } finally {
    unlockBtn.disabled = false;
    unlockBtn.textContent = 'Unlock';
  }
}

async function vaultRestoreFile(file) {
  var ok = await showConfirm('Restore from Vault?', '"' + file.name + '" will be restored to My Drive.', 'Restore');
  if (!ok) return;
  try {
    await fetchJSON('/api/vault/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'file', id: file.id })
    });
    showToast('Restored to My Drive', 'success');
    await loadVaultData();
  } catch (e) {
    showToast(e.message || 'Failed to restore', 'error');
  }
}

async function vaultRestoreFolder(folderId, folderName) {
  var ok = await showConfirm('Restore folder from Vault?', '"' + folderName + '" and its contents will be restored.', 'Restore');
  if (!ok) return;
  try {
    await fetchJSON('/api/vault/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'folder', id: folderId })
    });
    showToast('Restored to My Drive', 'success');
    await loadVaultData();
  } catch (e) {
    showToast(e.message || 'Failed to restore', 'error');
  }
}

async function lockVaultConfirm() {
  var ok = await showConfirm('Lock Vault?', 'This will immediately hide your private files.', 'Lock Everything');
  if (!ok) return;
  await lockVault();
}

async function lockVault() {
  try {
    await fetchJSON('/api/vault/lock', { method: 'POST' });
  } catch (e) { /* ignore */ }
  forceVaultLock();
}

function forceVaultLock() {
  vaultState.unlocked = false;
  vaultState.files = [];
  vaultState.folders = [];
  vaultState.breadcrumb = [];
  vaultState.currentFolderId = null;
  stopAutoLockTimer();
  updateVaultNav();
  if (state.currentView === 'vault') {
    showVaultLockScreen();
  }
}

function startAutoLockTimer() {
  stopAutoLockTimer();
  vaultState.autoLockRemaining = vaultState.autoLockSeconds;
  updateAutoLockDisplay();
  vaultState.autoLockTimer = setInterval(function() {
    vaultState.autoLockRemaining--;
    updateAutoLockDisplay();
    if (vaultState.autoLockRemaining <= 0) {
      forceVaultLock();
      showToast('Vault auto-locked due to inactivity', 'info');
    }
  }, 1000);
}

function stopAutoLockTimer() {
  if (vaultState.autoLockTimer) {
    clearInterval(vaultState.autoLockTimer);
    vaultState.autoLockTimer = null;
  }
}

function updateAutoLockDisplay() {
  var timerEl = document.getElementById('vault-autolock-timer');
  if (!timerEl) return;
  var mins = Math.floor(vaultState.autoLockRemaining / 60);
  var secs = vaultState.autoLockRemaining % 60;
  timerEl.textContent = String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
}

function resetAutoLockTimer() {
  if (vaultState.unlocked) {
    vaultState.autoLockRemaining = vaultState.autoLockSeconds;
    updateAutoLockDisplay();
  }
}

function navigateToFiles() {
  state.currentView = 'files';
  state.currentFolderId = null;
  document.querySelectorAll('.sidebar-nav .nav-item').forEach(function(b) { b.classList.remove('active'); });
  var filesBtn = document.querySelector('[data-view="files"]');
  if (filesBtn) filesBtn.classList.add('active');
  showMainViews();
  history.pushState({}, '', location.pathname);
  loadViewData('files');
}

async function handleVaultUpload(files) {
  if (!files.length) return;
  for (var i = 0; i < files.length; i++) {
    var file = files[i];
    var formData = new FormData();
    formData.append('file', file);
    if (vaultState.currentFolderId) {
      formData.append('folder_id', vaultState.currentFolderId);
    }
    try {
      await fetchJSON('/api/files/upload', { method: 'POST', body: formData });
      showToast('Uploaded ' + file.name, 'success');
    } catch (e) {
      showToast(e.message || 'Upload failed', 'error');
    }
  }
  await loadVaultData();
}

async function createVaultFolder() {
  var name = await showPrompt('New folder', 'Enter a name for the new folder.', 'Folder name');
  if (!name || !name.trim()) return;
  try {
    await fetchJSON('/api/folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), parent_id: vaultState.currentFolderId })
    });
    showToast('Folder created', 'success');
    await loadVaultData();
  } catch (e) {
    showToast(e.message || 'Failed to create folder', 'error');
  }
}

window.addEventListener('popstate', function(e) {
  if (state.currentView === 'vault') {
    var params = new URLSearchParams(window.location.search);
    var vfid = params.get('vault_folder');
    vaultState.currentFolderId = vfid ? parseInt(vfid) : null;
    loadVaultData();
  }
});

(function interceptVaultFetch() {
  var origFetchJSON = window.fetchJSON;
  if (!origFetchJSON) return;
  window.fetchJSON = function(url, options) {
    return origFetchJSON(url, options).catch(function(err) {
      if (err && err.message && err.message.toLowerCase().includes('vault is locked')) {
        forceVaultLock();
      }
      throw err;
    });
  };
})();
