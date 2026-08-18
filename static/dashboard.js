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
  pagination: null,
  shares: [],
};

document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  setupActivityListeners();
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

    // Handle view parameter in URL
    var viewParam = params.get('view');
    if (viewParam) {
      // Update currentView based on URL parameter
      state.currentView = viewParam;

      // Update active sidebar button
      document.querySelectorAll('.sidebar-nav .nav-item').forEach(b => b.classList.remove('active'));
      var viewBtn = document.querySelector('.sidebar-nav .nav-item[data-view="' + viewParam + '"]');
      if (viewBtn) {
        viewBtn.classList.add('active');
      }

      // Show the appropriate view
      if (viewParam === 'files') {
        hideAllViews();
        showMainContent();
        loadViewData('files');
      } else if (viewParam === 'shares') {
        hideAllViews();
        document.getElementById('shares-view').hidden = false;
        loadShares();
      } else if (viewParam === 'settings') {
        hideAllViews();
        document.getElementById('settings-view').hidden = false;
        // Update back button in settings toolbar
        const settingsBackBtn = document.getElementById('settings-back-btn');
        if (settingsBackBtn) {
          settingsBackBtn.textContent = '← Back';
          settingsBackBtn.onclick = () => {
            navigateToFiles();
          };
        }
        loadSettingsViewContent();
      } else if (viewParam === 'activity') {
        hideAllViews();
        document.getElementById('activity-view').hidden = false;
        loadActivity();
      } else if (viewParam === 'storage-intel') {
        hideAllViews();
        document.getElementById('storage-intel-view').hidden = false;
        loadStorageIntelligence();
      } else if (viewParam === 'vault') {
        // For vault, we need to call openVault but prevent recursion
        if (state.currentView !== 'vault') {
          openVault();
        }
      }
      return; // Skip the rest of the popstate handling
    }

    // Handle popstate for settings view (fallback for state changes)
    if (state.currentView === 'settings') {
      loadSettingsViewContent();
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
      if (view === 'shares') {
        state.currentView = 'shares';
        document.querySelectorAll('.sidebar-nav .nav-item').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        hideAllViews();
        document.getElementById('shares-view').hidden = false;
        loadShares();
        closeSidebar();
        return;
      }
      if (view === 'activity') {
        state.currentView = 'activity';
        document.querySelectorAll('.sidebar-nav .nav-item').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        hideAllViews();
        document.getElementById('activity-view').hidden = false;
        loadActivity();
        closeSidebar();
        return;
      }
      if (view === 'storage-intel') {
        state.currentView = 'storage-intel';
        document.querySelectorAll('.sidebar-nav .nav-item').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        hideAllViews();
        document.getElementById('storage-intel-view').hidden = false;
        loadStorageIntelligence();
        closeSidebar();
        return;
      }
      if (view === 'settings') {
        state.currentView = 'settings';
        document.querySelectorAll('.sidebar-nav .nav-item').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        hideAllViews();
        document.getElementById('settings-view').hidden = false;
        // Update back button in settings toolbar
        const settingsBackBtn = document.getElementById('settings-back-btn');
        if (settingsBackBtn) {
          settingsBackBtn.textContent = '← Back';
          settingsBackBtn.onclick = () => {
            navigateToFiles();
          };
        }
        history.pushState({ view: 'settings' }, '', '?view=settings');
        loadSettingsViewContent();
        closeSidebar();
        return;
      }
      state.currentView = view;
      document.querySelectorAll('.sidebar-nav .nav-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      showMainViews();
      if (view === 'settings') {
        loadSettingsViewContent();
      } else {
        loadViewData(view);
      }
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
  document.getElementById('share-require-password').addEventListener('change', function() {
    document.getElementById('share-password-group').hidden = !this.checked;
    if (this.checked) {
      document.getElementById('share-password').focus();
    }
  });
  document.querySelectorAll('input[name="share-expiry"]').forEach(function(radio) {
    radio.addEventListener('change', function() {
      document.getElementById('share-custom-expiry-group').hidden = this.value !== 'custom';
      if (this.value === 'custom') {
        document.getElementById('share-custom-expiry').focus();
      }
    });
  });
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
          <button class="soft-btn small folder-history-btn" type="button">&#128339;</button>
          <button class="soft-btn small folder-delete-btn" type="button">Delete</button>
        </div>
      `;
      card.querySelector('.folder-open-btn').addEventListener('click', () => navigateFolder(folder.id));
      card.querySelector('.folder-history-btn').addEventListener('click', () => openHistoryModal('folder', folder.id, folder.name));
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
      document.getElementById('share-result-meta').innerHTML = '';
      document.getElementById('share-modal-filename').textContent = escapeHtml(file.name);
      document.getElementById('create-share-btn').hidden = false;
      var shareForm = document.getElementById('share-form');
      shareForm.reset();
      document.getElementById('share-password-group').hidden = true;
      document.getElementById('share-custom-expiry-group').hidden = true;
      openModal('share-modal');
      break;
    case 'restore': restoreSingleFile(file); break;
    case 'permanent-delete': permanentDeleteSingleFile(file); break;
    case 'move': openMoveModal(file); break;
    case 'vault-move': vaultMoveFile(file); break;
    case 'vault-restore': vaultRestoreFile(file); break;
    case 'history': openHistoryModal('file', file.id, file.name); break;
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
  var expiryRadio = document.querySelector('input[name="share-expiry"]:checked');
  const expiry = expiryRadio ? expiryRadio.value : '';
  const canDownload = document.getElementById('share-can-download').checked;
  const requirePassword = document.getElementById('share-require-password').checked;
  const password = document.getElementById('share-password').value;
  const oneTime = document.getElementById('share-one-time').checked;
  const downloadLimit = document.getElementById('share-download-limit').value;

  let expiresAt = null;
  if (expiry === '1h') {
    expiresAt = new Date(Date.now() + 60 * 60 * 1000).toISOString();
  } else if (expiry === '1d') {
    expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
  } else if (expiry === '7d') {
    expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
  } else if (expiry === 'custom') {
    const customExpiry = document.getElementById('share-custom-expiry').value;
    if (customExpiry) {
      const dt = new Date(customExpiry);
      if (dt > new Date()) {
        expiresAt = dt.toISOString();
      }
    }
  }

  const body = {
    can_view: true,
    can_download: canDownload,
    expires_at: expiresAt,
    one_time: oneTime,
  };

  if (requirePassword && password) {
    body.password = password;
  }

  if (downloadLimit) {
    body.download_limit = parseInt(downloadLimit);
  }

  var createBtn = document.getElementById('create-share-btn');
  createBtn.disabled = true;
  createBtn.textContent = 'Creating...';

  try {
    const data = await fetchJSON(`${routes.fileBase}${state.shareTarget.id}/share`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    document.getElementById('share-url-input').value = data.share.url;
    document.getElementById('share-result').hidden = false;
    createBtn.hidden = true;

    var metaHtml = '';
    if (data.share.expires_at) {
      var expDate = new Date(data.share.expires_at);
      var now = new Date();
      var diff = expDate - now;
      if (diff > 0) {
        var days = Math.floor(diff / (1000 * 60 * 60 * 24));
        var hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        if (days > 0) metaHtml += '<span class="chip neutral">&#9200; Expires in ' + days + ' day' + (days === 1 ? '' : 's') + '</span>';
        else metaHtml += '<span class="chip neutral">&#9200; Expires in ' + hours + ' hour' + (hours === 1 ? '' : 's') + '</span>';
      }
    }
    if (data.share.one_time) metaHtml += '<span class="chip neutral">&#9889; One-time</span>';
    if (data.share.has_password) metaHtml += '<span class="chip neutral">&#128274; Password</span>';
    if (!data.share.can_download) metaHtml += '<span class="chip neutral">&#128269; Preview only</span>';
    if (data.share.download_limit) metaHtml += '<span class="chip neutral">&#11015; Max ' + data.share.download_limit + '</span>';

    document.getElementById('share-result-meta').innerHTML = metaHtml;
    showToast('Share link created', 'success');
  } catch (error) {
    showToast(error.message || 'Failed to create share link', 'error');
  } finally {
    createBtn.disabled = false;
    createBtn.textContent = 'Create Secure Link';
  }
}

function copyShareUrl() {
  const input = document.getElementById('share-url-input');
  navigator.clipboard.writeText(input.value)
    .then(() => showToast('Link copied to clipboard', 'success'))
    .catch(() => { input.select(); document.execCommand('copy'); showToast('Link copied', 'success'); });
}

async function loadShares() {
  try {
    const data = await fetchJSON('/api/shares');
    state.shares = data.shares || [];
    renderShares();
  } catch (error) {
    showToast(error.message || 'Failed to load shares', 'error');
  }
}

function renderShares() {
  const container = document.getElementById('shares-list');
  const emptyState = document.getElementById('shares-empty-state');
  const subtitle = document.getElementById('shares-header-subtitle');

  if (!container) return;

  const shares = state.shares || [];
  subtitle.textContent = shares.length ? shares.length + ' active share' + (shares.length === 1 ? '' : 's') : 'No active shares';

  if (!shares.length) {
    container.innerHTML = '';
    emptyState.hidden = false;
    return;
  }

  emptyState.hidden = true;
  container.innerHTML = '';

  shares.forEach(function(share) {
    var item = document.createElement('div');
    item.className = 'share-item';
    item.dataset.shareId = share.id;

    var metaHtml = '';
    metaHtml += '<span>&#128279; ' + share.download_count + ' download' + (share.download_count === 1 ? '' : 's') + '</span>';

    if (share.download_limit) {
      metaHtml += '<span>/ ' + share.download_limit + ' limit</span>';
    } else {
      metaHtml += '<span>No limit</span>';
    }
    if (share.expires_at) {
      var expDate = new Date(share.expires_at);
      var now = new Date();
      if (expDate > now) {
        var diff = expDate - now;
        var days = Math.floor(diff / (1000 * 60 * 60 * 24));
        var hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        var mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        if (days > 0) {
          metaHtml += '<span>&#9200; Expires in ' + days + ' day' + (days === 1 ? '' : 's') + '</span>';
        } else if (hours > 0) {
          metaHtml += '<span>&#9200; Expires in ' + hours + ' hour' + (hours === 1 ? '' : 's') + '</span>';
        } else {
          metaHtml += '<span>&#9200; Expires in ' + mins + ' min' + (mins === 1 ? '' : 's') + '</span>';
        }
      } else {
        metaHtml += '<span style="color:var(--danger)">&#9200; Expired</span>';
      }
    }
    if (share.one_time) {
      metaHtml += '<span>&#9889; One-time link</span>';
    }

    var chipsHtml = '';
    if (share.has_password) {
      chipsHtml += '<span class="chip neutral">&#128274; Password</span>';
    }
    if (share.can_download) {
      chipsHtml += '<span class="chip success">&#11015; Download enabled</span>';
    } else {
      chipsHtml += '<span class="chip neutral">&#128269; Preview only</span>';
    }

    item.innerHTML = '<div class="share-item-info">' +
      '<div class="share-item-name">' + escapeHtml(share.filename) + '</div>' +
      '<div class="share-item-meta">' + metaHtml + '</div>' +
      '<div class="share-item-chips">' + chipsHtml + '</div>' +
      '</div>' +
      '<div class="share-item-actions">' +
      '<button class="soft-btn small" type="button" data-action="copy">&#128203; Copy</button>' +
      '<button class="soft-btn small danger-btn" type="button" data-action="revoke">&#128683; Revoke</button>' +
      '</div>';

    item.querySelector('[data-action="copy"]').addEventListener('click', function() {
      navigator.clipboard.writeText(share.url)
        .then(function() { showToast('Link copied to clipboard', 'success'); })
        .catch(function() { showToast('Failed to copy', 'error'); });
    });

    item.querySelector('[data-action="revoke"]').addEventListener('click', function() {
      revokeShare(share.id, share.filename);
    });

    container.appendChild(item);
  });

  document.getElementById('nav-count-shares').textContent = shares.length;
}

async function revokeShare(shareId, filename) {
  var ok = await showConfirm('Revoke share?', 'The share link for "' + filename + '" will be immediately disabled. This cannot be undone.', 'Revoke', true);
  if (!ok) return;

  try {
    await fetchJSON('/api/shares/' + shareId + '/revoke', { method: 'DELETE' });
    state.shares = state.shares.filter(function(s) { return s.id !== shareId; });
    renderShares();
    showToast('Share link revoked', 'success');
  } catch (error) {
    showToast(error.message || 'Failed to revoke share', 'error');
  }
}

function showMainViews() {
  document.getElementById('shares-view').hidden = true;
  document.getElementById('vault-view').hidden = true;
  document.getElementById('vault-lock-screen').hidden = true;
  document.getElementById('activity-view').hidden = true;
  document.getElementById('storage-intel-view').hidden = true;
  document.getElementById('settings-view').hidden = true;
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

// ---------------------------------------------------------------------------
// Activity Timeline (Phase 5B)
// ---------------------------------------------------------------------------

const ACTIVITY_ICONS = {
  FILE_UPLOADED: '&#11015;',
  FILE_DOWNLOADED: '&#11015;',
  FILE_PREVIEWED: '&#128065;',
  FILE_RENAMED: '&#9998;',
  FILE_FAVORITED: '&#9733;',
  FILE_UNFAVORITED: '&#9734;',
  FILE_MOVED: '&#128194;',
  FILE_DELETED: '&#128465;',
  FILE_RESTORED: '&#128260;',
  FILE_PERMANENTLY_DELETED: '&#128465;',
  FOLDER_CREATED: '&#128193;',
  FOLDER_RENAMED: '&#9998;',
  FOLDER_MOVED: '&#128194;',
  FOLDER_DELETED: '&#128465;',
  FOLDER_RESTORED: '&#128260;',
  FOLDER_PERMANENTLY_DELETED: '&#128465;',
  VAULT_UNLOCKED: '&#128275;',
  VAULT_LOCKED: '&#128274;',
  FILE_MOVED_TO_VAULT: '&#128274;',
  FILE_RESTORED_FROM_VAULT: '&#128275;',
  FOLDER_MOVED_TO_VAULT: '&#128274;',
  FOLDER_RESTORED_FROM_VAULT: '&#128275;',
  SHARE_CREATED: '&#128279;',
  SHARE_ACCESSED: '&#128279;',
  SHARE_REVOKED: '&#128279;',
  WEBDAV_UPLOAD: '&#9729;',
  WEBDAV_DOWNLOAD: '&#9729;',
  WEBDAV_MOVE: '&#9729;',
  WEBDAV_DELETE: '&#9729;',
  WEBDAV_FOLDER_CREATED: '&#9729;',
};

const ACTIVITY_COLORS = {
  FILE_UPLOADED: 'activity-color-green',
  FILE_DOWNLOADED: 'activity-color-blue',
  FILE_PREVIEWED: 'activity-color-blue',
  FILE_RENAMED: 'activity-color-yellow',
  FILE_FAVORITED: 'activity-color-yellow',
  FILE_UNFAVORITED: 'activity-color-muted',
  FILE_MOVED: 'activity-color-blue',
  FILE_DELETED: 'activity-color-red',
  FILE_RESTORED: 'activity-color-green',
  FILE_PERMANENTLY_DELETED: 'activity-color-red',
  FOLDER_CREATED: 'activity-color-green',
  FOLDER_RENAMED: 'activity-color-yellow',
  FOLDER_MOVED: 'activity-color-blue',
  FOLDER_DELETED: 'activity-color-red',
  FOLDER_RESTORED: 'activity-color-green',
  FOLDER_PERMANENTLY_DELETED: 'activity-color-red',
  VAULT_UNLOCKED: 'activity-color-green',
  VAULT_LOCKED: 'activity-color-muted',
  FILE_MOVED_TO_VAULT: 'activity-color-purple',
  FILE_RESTORED_FROM_VAULT: 'activity-color-green',
  FOLDER_MOVED_TO_VAULT: 'activity-color-purple',
  FOLDER_RESTORED_FROM_VAULT: 'activity-color-green',
  SHARE_CREATED: 'activity-color-blue',
  SHARE_ACCESSED: 'activity-color-blue',
  SHARE_REVOKED: 'activity-color-red',
  WEBDAV_UPLOAD: 'activity-color-blue',
  WEBDAV_DOWNLOAD: 'activity-color-blue',
  WEBDAV_MOVE: 'activity-color-yellow',
  WEBDAV_DELETE: 'activity-color-red',
  WEBDAV_FOLDER_CREATED: 'activity-color-blue',
};

const ACTIVITY_FILTER_MAP = {
  all: null,
  files: 'file',
  folders: 'folder',
  vault: 'vault',
  shares: 'share',
  webdav: 'webdav',
};

const activityState = {
  events: [],
  filter: 'all',
  offset: 0,
  limit: 50,
  hasMore: true,
  loading: false,
};

function describeEvent(ev) {
  const meta = ev.metadata ? (typeof ev.metadata === 'string' ? safeParseJson(ev.metadata) : ev.metadata) : {};
  const fn = meta.filename || meta.name || '';
  const oldName = meta.old_name || '';
  const newName = meta.new_name || '';
  switch (ev.event_type) {
    case 'FILE_UPLOADED': return { text: 'Uploaded', detail: fn };
    case 'FILE_DOWNLOADED': return { text: 'Downloaded', detail: fn };
    case 'FILE_PREVIEWED': return { text: 'Previewed', detail: fn };
    case 'FILE_RENAMED': return { text: 'Renamed', detail: oldName && newName ? `${oldName} \u2192 ${newName}` : fn };
    case 'FILE_FAVORITED': return { text: 'Favorited', detail: fn };
    case 'FILE_UNFAVORITED': return { text: 'Unfavorited', detail: fn };
    case 'FILE_MOVED': return { text: 'Moved', detail: fn };
    case 'FILE_DELETED': return { text: 'Deleted', detail: fn };
    case 'FILE_RESTORED': return { text: 'Restored', detail: fn };
    case 'FILE_PERMANENTLY_DELETED': return { text: 'Permanently deleted', detail: fn };
    case 'FOLDER_CREATED': return { text: 'Created folder', detail: meta.name || '' };
    case 'FOLDER_RENAMED': return { text: 'Renamed folder', detail: oldName && newName ? `${oldName} \u2192 ${newName}` : meta.name || '' };
    case 'FOLDER_MOVED': return { text: 'Moved folder', detail: meta.name || '' };
    case 'FOLDER_DELETED': return { text: 'Deleted folder', detail: meta.name || '' };
    case 'FOLDER_RESTORED': return { text: 'Restored folder', detail: meta.name || '' };
    case 'FOLDER_PERMANENTLY_DELETED': return { text: 'Permanently deleted folder', detail: meta.name || '' };
    case 'VAULT_UNLOCKED': return { text: 'Unlocked Vault', detail: '' };
    case 'VAULT_LOCKED': return { text: 'Locked Vault', detail: '' };
    case 'FILE_MOVED_TO_VAULT': return { text: 'Moved to Vault', detail: fn };
    case 'FILE_RESTORED_FROM_VAULT': return { text: 'Restored from Vault', detail: fn };
    case 'FOLDER_MOVED_TO_VAULT': return { text: 'Moved folder to Vault', detail: meta.name || '' };
    case 'FOLDER_RESTORED_FROM_VAULT': return { text: 'Restored folder from Vault', detail: meta.name || '' };
    case 'SHARE_CREATED': return { text: 'Created share link', detail: fn };
    case 'SHARE_ACCESSED': return { text: 'Share accessed', detail: fn };
    case 'SHARE_REVOKED': return { text: 'Revoked share link', detail: fn };
    case 'WEBDAV_UPLOAD': return { text: 'Uploaded via WebDAV', detail: fn };
    case 'WEBDAV_DOWNLOAD': return { text: 'Downloaded via WebDAV', detail: fn };
    case 'WEBDAV_MOVE': return { text: 'Renamed via WebDAV', detail: oldName && newName ? `${oldName} \u2192 ${newName}` : fn };
    case 'WEBDAV_DELETE': return { text: 'Deleted via WebDAV', detail: fn };
    case 'WEBDAV_FOLDER_CREATED': return { text: 'Created folder via WebDAV', detail: meta.name || '' };
    default: return { text: ev.event_type, detail: fn };
  }
}

function safeParseJson(str) {
  try { return JSON.parse(str); } catch (e) { return {}; }
}

function formatActivityTime(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  } catch (e) { return ''; }
}

function formatActivityDate(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return '';
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const eventDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff = today - eventDay;
    if (diff < 86400000 && today.getDate() === eventDay.getDate()) return 'Today';
    if (diff < 172800000) return 'Yesterday';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined });
  } catch (e) { return ''; }
}

function formatHistoryTime(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) + ', ' + d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  } catch (e) { return ''; }
}

function groupEventsByDate(events) {
  const groups = [];
  let currentLabel = '';
  for (const ev of events) {
    const label = formatActivityDate(ev.created_at);
    if (label !== currentLabel) {
      currentLabel = label;
      groups.push({ label, events: [] });
    }
    groups[groups.length - 1].events.push(ev);
  }
  return groups;
}

async function loadActivity(reset) {
  if (activityState.loading) return;
  if (reset) {
    activityState.events = [];
    activityState.offset = 0;
    activityState.hasMore = true;
  }
  activityState.loading = true;
  document.getElementById('activity-loading').hidden = false;
  document.getElementById('activity-empty').hidden = true;
  document.getElementById('activity-timeline').innerHTML = '';
  document.getElementById('activity-load-more').hidden = true;
  try {
    const resourceType = ACTIVITY_FILTER_MAP[activityState.filter];
    const params = ['limit=' + activityState.limit, 'offset=' + activityState.offset];
    if (resourceType) params.push('resource_type=' + resourceType);
    const url = '/api/user/activity?' + params.join('&');
    const result = await fetchJSON(url);
    const newEvents = result.activities || [];
    if (reset) activityState.events = newEvents;
    else activityState.events = activityState.events.concat(newEvents);
    activityState.hasMore = newEvents.length >= activityState.limit;
    activityState.offset = activityState.events.length;
    renderActivity();
  } catch (error) {
    showToast(error.message || 'Failed to load activity', 'error');
  } finally {
    activityState.loading = false;
    document.getElementById('activity-loading').hidden = true;
  }
}

function renderActivity() {
  const container = document.getElementById('activity-timeline');
  const emptyEl = document.getElementById('activity-empty');
  const loadMoreEl = document.getElementById('activity-load-more');
  container.innerHTML = '';
  if (!activityState.events.length) {
    emptyEl.hidden = false;
    loadMoreEl.hidden = true;
    return;
  }
  emptyEl.hidden = true;
  loadMoreEl.hidden = !activityState.hasMore;
  const groups = groupEventsByDate(activityState.events);
  for (const group of groups) {
    const dateEl = document.createElement('div');
    dateEl.className = 'activity-date-group';
    dateEl.setAttribute('role', 'listitem');
    dateEl.innerHTML = '<div class="activity-date-label">' + escapeHtml(group.label) + '</div>';
    for (const ev of group.events) {
      const desc = describeEvent(ev);
      const icon = ACTIVITY_ICONS[ev.event_type] || '&#128196;';
      const colorClass = ACTIVITY_COLORS[ev.event_type] || 'activity-color-muted';
      const time = formatActivityTime(ev.created_at);
      const eventEl = document.createElement('div');
      eventEl.className = 'activity-event';
      eventEl.setAttribute('role', 'listitem');
      eventEl.tabIndex = 0;
      eventEl.dataset.eventId = ev.id || '';
      eventEl.dataset.eventType = ev.event_type || '';
      eventEl.dataset.resourceType = ev.resource_type || '';
      eventEl.dataset.resourceId = ev.resource_id || '';
      eventEl.dataset.metadata = ev.metadata || '';
      eventEl.dataset.createdAt = ev.created_at || '';
      eventEl.innerHTML =
        '<div class="activity-event-icon ' + colorClass + '">' + icon + '</div>' +
        '<div class="activity-event-content">' +
          '<div class="activity-event-text">' + escapeHtml(desc.text) + '</div>' +
          (desc.detail ? '<div class="activity-event-detail">' + escapeHtml(desc.detail) + '</div>' : '') +
        '</div>' +
        '<div class="activity-event-time">' + escapeHtml(time) + '</div>';
      eventEl.addEventListener('click', function() { openEventDetails(this); });
      eventEl.addEventListener('keydown', function(e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openEventDetails(this); } });
      dateEl.appendChild(eventEl);
    }
    container.appendChild(dateEl);
  }
}

function openEventDetails(el) {
  const eventType = el.dataset.eventType;
  const resourceType = el.dataset.resourceType;
  const resourceId = el.dataset.resourceId;
  const metaStr = el.dataset.metadata;
  const createdAt = el.dataset.createdAt;
  const meta = metaStr ? safeParseJson(metaStr) : {};
  const desc = describeEvent({ event_type: eventType, metadata: meta });
  document.getElementById('event-details-title').textContent = desc.text;
  document.getElementById('event-details-subtitle').textContent = desc.detail || '';
  const body = document.getElementById('event-details-body');
  let html = '<div class="event-detail-row"><span class="event-detail-label">Time</span><span class="event-detail-value">' + escapeHtml(formatHistoryTime(createdAt)) + '</span></div>';
  if (eventType === 'FILE_RENAMED' || eventType === 'FOLDER_RENAMED' || eventType === 'WEBDAV_MOVE') {
    if (meta.old_name) html += '<div class="event-detail-row"><span class="event-detail-label">Old name</span><span class="event-detail-value">' + escapeHtml(meta.old_name) + '</span></div>';
    if (meta.new_name) html += '<div class="event-detail-row"><span class="event-detail-label">New name</span><span class="event-detail-value">' + escapeHtml(meta.new_name) + '</span></div>';
  }
  if (meta.size !== undefined && meta.size !== null) {
    html += '<div class="event-detail-row"><span class="event-detail-label">Size</span><span class="event-detail-value">' + escapeHtml(formatSize(meta.size)) + '</span></div>';
  }
  if (meta.mime_type) {
    html += '<div class="event-detail-row"><span class="event-detail-label">Type</span><span class="event-detail-value">' + escapeHtml(meta.mime_type) + '</span></div>';
  }
  body.innerHTML = html;
  openModal('event-details-modal');
}

function openHistoryModal(resourceType, resourceId, resourceName) {
  document.getElementById('history-modal-title').textContent = resourceType === 'folder' ? 'Folder History' : 'File History';
  document.getElementById('history-modal-filename').textContent = resourceName || '';
  document.getElementById('history-modal-body').innerHTML = '<div class="activity-loading"><div class="skeleton-timeline"><div class="skeleton skeleton-event"></div><div class="skeleton skeleton-event"></div></div></div>';
  openModal('history-modal');
  loadHistoryEvents(resourceType, resourceId);
}

async function loadHistoryEvents(resourceType, resourceId) {
  try {
    const url = '/api/user/activity?resource_type=' + encodeURIComponent(resourceType) + '&limit=50&offset=0';
    const result = await fetchJSON(url);
    let events = result.activities || [];
    events = events.filter(function(ev) { return String(ev.resource_id) === String(resourceId); });
    renderHistoryEvents(events);
  } catch (error) {
    document.getElementById('history-modal-body').innerHTML = '<div class="activity-empty"><p>Failed to load history.</p></div>';
  }
}

function renderHistoryEvents(events) {
  const body = document.getElementById('history-modal-body');
  if (!events.length) {
    body.innerHTML = '<div class="activity-empty"><p>No history found.</p></div>';
    return;
  }
  let html = '<div class="history-timeline">';
  for (const ev of events) {
    const desc = describeEvent(ev);
    const icon = ACTIVITY_ICONS[ev.event_type] || '&#128196;';
    const colorClass = ACTIVITY_COLORS[ev.event_type] || 'activity-color-muted';
    const time = formatHistoryTime(ev.created_at);
    html += '<div class="history-event">' +
      '<div class="activity-event-icon ' + colorClass + '">' + icon + '</div>' +
      '<div class="history-event-content">' +
        '<div class="activity-event-text">' + escapeHtml(desc.text) + '</div>' +
        '<div class="history-event-time">' + escapeHtml(time) + '</div>' +
      '</div>' +
    '</div>';
  }
  html += '</div>';
  body.innerHTML = html;
}

function setupActivityListeners() {
  document.querySelectorAll('.activity-filter-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.activity-filter-btn').forEach(function(b) { b.classList.remove('active'); b.setAttribute('aria-checked', 'false'); });
      btn.classList.add('active');
      btn.setAttribute('aria-checked', 'true');
      activityState.filter = btn.dataset.filter;
      loadActivity(true);
    });
  });
  document.getElementById('activity-refresh-btn').addEventListener('click', function() { loadActivity(true); });
  document.getElementById('activity-load-more-btn').addEventListener('click', function() { loadActivity(false); });
  document.getElementById('activity-empty-goto-drive').addEventListener('click', function() {
    document.querySelector('[data-view="files"]').click();
  });
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

  var sharesRefreshBtn = document.getElementById('shares-refresh-btn');
  if (sharesRefreshBtn) {
    sharesRefreshBtn.addEventListener('click', function() {
      loadShares();
    });
  }
}

/* ===== Storage Intelligence ===== */

const siCategoryIcons = {
  images: '\uD83D\uDDBC\uFE0F',
  videos: '\uD83C\uDFAC',
  audio: '\uD83C\uDFB5',
  documents: '\uD83D\uDCC4',
  archives: '\uD83D\uDCE6',
  other: '\uD83D\uDCC2'
};

const siCategoryLabels = {
  images: 'Images',
  videos: 'Videos',
  audio: 'Audio',
  documents: 'Documents',
  archives: 'Archives',
  other: 'Other'
};

const siCategoryColors = {
  images: '#34d399',
  videos: '#818cf8',
  audio: '#fbbf24',
  documents: '#60a5fa',
  archives: '#f472b6',
  other: '#94a3b8'
};

function siFileIcon(mimeType) {
  if (!mimeType) return '\uD83D\uDCC2';
  var m = mimeType.toLowerCase();
  if (m.startsWith('image/')) return '\uD83D\uDDBC\uFE0F';
  if (m.startsWith('video/')) return '\uD83C\uDFAC';
  if (m.startsWith('audio/')) return '\uD83C\uDFB5';
  if (m.includes('pdf')) return '\uD83D\uDCC4';
  if (m.includes('word') || m.includes('document')) return '\uD83D\uDCC3';
  if (m.includes('sheet') || m.includes('excel') || m.includes('csv')) return '\uD83D\uDCCA';
  if (m.includes('presentation') || m.includes('powerpoint')) return '\uD83D\uDCCA';
  if (m.includes('zip') || m.includes('rar') || m.includes('7z') || m.includes('tar') || m.includes('gzip')) return '\uD83D\uDCE6';
  if (m.startsWith('text/')) return '\uD83D\uDCC4';
  if (m.includes('json') || m.includes('xml')) return '\uD83D\uDCC4';
  return '\uD83D\uDCC2';
}

function siFileTypeCategory(mimeType) {
  if (!mimeType) return 'other';
  var m = mimeType.toLowerCase();
  if (m.startsWith('image/')) return 'images';
  if (m.startsWith('video/')) return 'videos';
  if (m.startsWith('audio/')) return 'audio';
  if (m.includes('pdf') || m.includes('word') || m.includes('document') || m.includes('sheet') || m.includes('excel') || m.includes('csv') || m.includes('presentation') || m.includes('powerpoint') || m.startsWith('text/') || m.includes('json') || m.includes('xml')) return 'documents';
  if (m.includes('zip') || m.includes('rar') || m.includes('7z') || m.includes('tar') || m.includes('gzip')) return 'archives';
  return 'other';
}

var siState = { data: null, loading: false };

function showSiLoading() {
  document.getElementById('si-loading').hidden = false;
  document.getElementById('si-error').hidden = true;
  document.getElementById('si-empty').hidden = true;
  document.getElementById('si-content').hidden = true;
}

function showSiError() {
  document.getElementById('si-loading').hidden = true;
  document.getElementById('si-error').hidden = false;
  document.getElementById('si-empty').hidden = true;
  document.getElementById('si-content').hidden = true;
}

function showSiEmpty() {
  document.getElementById('si-loading').hidden = true;
  document.getElementById('si-error').hidden = true;
  document.getElementById('si-empty').hidden = false;
  document.getElementById('si-content').hidden = true;
}

function showSiContent() {
  document.getElementById('si-loading').hidden = true;
  document.getElementById('si-error').hidden = true;
  document.getElementById('si-empty').hidden = true;
  document.getElementById('si-content').hidden = false;
}

async function loadStorageIntelligence() {
  if (siState.loading) return;
  siState.loading = true;
  showSiLoading();

  try {
    var data = await fetchJSON('/api/storage/stats');
    siState.data = data;
    renderStorageIntelligence(data);
  } catch (err) {
    showSiError();
  } finally {
    siState.loading = false;
  }
}

function renderStorageIntelligence(data) {
  if (!data || data.file_count === 0 && data.folder_count === 0) {
    showSiEmpty();
    return;
  }

  showSiContent();

  document.getElementById('si-hero-size').textContent = formatSize(data.total_size || 0);
  document.getElementById('si-hero-files').textContent = (data.file_count || 0) + ' file' + (data.file_count === 1 ? '' : 's');
  document.getElementById('si-hero-folders').textContent = (data.folder_count || 0) + ' folder' + (data.folder_count === 1 ? '' : 's');

  renderSiChart(data);
  renderSiBreakdown(data);
  renderSiLargestFiles(data);
  renderSiRecentFiles(data);
  renderSiFolderOverview(data);
}

function renderSiChart(data) {
  var container = document.getElementById('si-hero-chart');
  var breakdown = data.type_breakdown || {};
  var categories = ['images', 'videos', 'audio', 'documents', 'archives', 'other'];
  var segments = [];
  var totalBytes = data.total_size || 0;

  categories.forEach(function(cat) {
    var catData = breakdown[cat];
    if (catData && catData.bytes > 0) {
      segments.push({ cat: cat, bytes: catData.bytes, pct: totalBytes > 0 ? (catData.bytes / totalBytes * 100) : 0 });
    }
  });

  if (segments.length === 0) {
    container.innerHTML = '<div class="si-chart-empty">No data</div>';
    container.setAttribute('aria-label', 'No storage data');
    return;
  }

  var size = 140;
  var cx = size / 2;
  var cy = size / 2;
  var r = 54;
  var circumference = 2 * Math.PI * r;
  var cumulative = 0;
  var titleParts = [];

  var svg = '<svg viewBox="0 0 ' + size + ' ' + size + '" class="si-donut" role="img" aria-label="Storage distribution">';

  segments.forEach(function(seg, i) {
    var pct = seg.pct / 100;
    var dashLen = circumference * pct;
    var dashOff = -circumference * cumulative;
    svg += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + siCategoryColors[seg.cat] + '" stroke-width="16" stroke-dasharray="' + dashLen.toFixed(2) + ' ' + (circumference - dashLen).toFixed(2) + '" stroke-dashoffset="' + dashOff.toFixed(2) + '" class="si-donut-seg" />';
    cumulative += pct;
    titleParts.push(siCategoryLabels[seg.cat] + ': ' + seg.pct.toFixed(1) + '%');
  });

  svg += '<text x="' + cx + '" y="' + (cy - 4) + '" text-anchor="middle" class="si-donut-center-size">' + formatSize(totalBytes) + '</text>';
  svg += '<text x="' + cx + '" y="' + (cy + 14) + '" text-anchor="middle" class="si-donut-center-label">used</text>';
  svg += '</svg>';

  container.innerHTML = svg;
  container.setAttribute('aria-label', 'Storage distribution: ' + titleParts.join(', '));
}

function renderSiBreakdown(data) {
  var container = document.getElementById('si-breakdown');
  var breakdown = data.type_breakdown || {};
  var categories = ['images', 'videos', 'audio', 'documents', 'archives', 'other'];
  var html = '';

  categories.forEach(function(cat) {
    var catData = breakdown[cat] || { count: 0, bytes: 0, percentage: 0 };
    var count = catData.count || 0;
    var bytes = catData.bytes || 0;
    var pct = catData.percentage || 0;

    html += '<div class="si-breakdown-card panel" role="listitem">';
    html += '<div class="si-bc-icon" style="background:' + siCategoryColors[cat] + '22;color:' + siCategoryColors[cat] + '">' + siCategoryIcons[cat] + '</div>';
    html += '<div class="si-bc-info">';
    html += '<div class="si-bc-name">' + escapeHtml(siCategoryLabels[cat]) + '</div>';
    html += '<div class="si-bc-count">' + count + ' file' + (count === 1 ? '' : 's') + '</div>';
    html += '<div class="si-bc-size">' + formatSize(bytes) + '</div>';
    html += '</div>';
    html += '<div class="si-bc-pct">' + pct.toFixed(1) + '%</div>';
    html += '</div>';
  });

  container.innerHTML = html;
}

function renderSiLargestFiles(data) {
  var container = document.getElementById('si-largest-files');
  var files = data.largest_files || [];

  if (files.length === 0) {
    container.innerHTML = '<div class="si-list-empty">No files yet</div>';
    return;
  }

  var html = '';
  files.forEach(function(file, idx) {
    var icon = siFileIcon(file.mime_type);
    var cat = siFileTypeCategory(file.mime_type);
    var color = siCategoryColors[cat] || siCategoryColors.other;

    html += '<div class="si-file-item" role="listitem" tabindex="0" data-file-id="' + file.id + '">';
    html += '<div class="si-file-rank">' + (idx + 1) + '</div>';
    html += '<div class="si-file-icon" style="color:' + color + '">' + icon + '</div>';
    html += '<div class="si-file-details">';
    html += '<div class="si-file-name" title="' + escapeHtml(file.filename) + '">' + escapeHtml(file.filename) + '</div>';
    html += '<div class="si-file-meta">' + formatSize(file.size || 0) + '</div>';
    html += '</div>';
    html += '<div class="si-file-actions">';
    html += '<button class="soft-btn small" type="button" data-action="preview" data-file-id="' + file.id + '" aria-label="Preview ' + escapeHtml(file.filename) + '">Preview</button>';
    html += '<button class="soft-btn small" type="button" data-action="download" data-file-id="' + file.id + '" aria-label="Download ' + escapeHtml(file.filename) + '">Download</button>';
    html += '</div>';
    html += '</div>';
  });

  container.innerHTML = html;

  container.querySelectorAll('.si-file-item').forEach(function(item) {
    item.addEventListener('click', function(e) {
      if (e.target.closest('.si-file-actions')) return;
      var fid = parseInt(item.dataset.fileId);
      var file = findFileById(fid);
      if (file) handleFileAction('preview', file);
    });
    item.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        var fid = parseInt(item.dataset.fileId);
        var file = findFileById(fid);
        if (file) handleFileAction('preview', file);
      }
    });
  });

  container.querySelectorAll('[data-action]').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      var fid = parseInt(btn.dataset.fileId);
      var file = findFileById(fid);
      if (file) handleFileAction(btn.dataset.action, file);
    });
  });
}

function renderSiRecentFiles(data) {
  var container = document.getElementById('si-recent-files');
  var files = data.recent_files || [];

  if (files.length === 0) {
    container.innerHTML = '<div class="si-list-empty">No files yet</div>';
    return;
  }

  var html = '';
  files.forEach(function(file) {
    var icon = siFileIcon(file.mime_type);
    var cat = siFileTypeCategory(file.mime_type);
    var color = siCategoryColors[cat] || siCategoryColors.other;

    html += '<div class="si-file-item" role="listitem" tabindex="0" data-file-id="' + file.id + '">';
    html += '<div class="si-file-icon" style="color:' + color + '">' + icon + '</div>';
    html += '<div class="si-file-details">';
    html += '<div class="si-file-name" title="' + escapeHtml(file.filename) + '">' + escapeHtml(file.filename) + '</div>';
    html += '<div class="si-file-meta">' + formatSize(file.size || 0) + ' \u00B7 ' + formatDate(file.uploaded_at) + '</div>';
    html += '</div>';
    html += '<div class="si-file-actions">';
    html += '<button class="soft-btn small" type="button" data-action="preview" data-file-id="' + file.id + '" aria-label="Preview ' + escapeHtml(file.filename) + '">Preview</button>';
    html += '<button class="soft-btn small" type="button" data-action="download" data-file-id="' + file.id + '" aria-label="Download ' + escapeHtml(file.filename) + '">Download</button>';
    html += '</div>';
    html += '</div>';
  });

  container.innerHTML = html;

  container.querySelectorAll('.si-file-item').forEach(function(item) {
    item.addEventListener('click', function(e) {
      if (e.target.closest('.si-file-actions')) return;
      var fid = parseInt(item.dataset.fileId);
      var file = findFileById(fid);
      if (file) handleFileAction('preview', file);
    });
    item.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        var fid = parseInt(item.dataset.fileId);
        var file = findFileById(fid);
        if (file) handleFileAction('preview', file);
      }
    });
  });

  container.querySelectorAll('[data-action]').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      var fid = parseInt(btn.dataset.fileId);
      var file = findFileById(fid);
      if (file) handleFileAction(btn.dataset.action, file);
    });
  });
}

function renderSiFolderOverview(data) {
  var count = data.folder_count || 0;
  document.getElementById('si-folder-count').textContent = count + ' folder' + (count === 1 ? '' : 's');
}

function findFileById(id) {
  var all = (state.allFiles || []).concat(state.files || []);
  for (var i = 0; i < all.length; i++) {
    if (all[i].id === id) return all[i];
  }
  return { id: id, name: 'File', type: 'others', size: 0 };
}

document.addEventListener('DOMContentLoaded', function() {
  var siRefreshBtn = document.getElementById('si-refresh-btn');
  if (siRefreshBtn) {
    siRefreshBtn.addEventListener('click', function() { loadStorageIntelligence(); });
  }
  var siRetryBtn = document.getElementById('si-retry-btn');
  if (siRetryBtn) {
    siRetryBtn.addEventListener('click', function() { loadStorageIntelligence(); });
  }
  var siGotoDriveBtn = document.getElementById('si-goto-drive-btn');
  if (siGotoDriveBtn) {
    siGotoDriveBtn.addEventListener('click', function() {
      document.querySelectorAll('.sidebar-nav .nav-item').forEach(function(b) { b.classList.remove('active'); });
      var filesBtn = document.querySelector('.sidebar-nav .nav-item[data-view="files"]');
      if (filesBtn) filesBtn.classList.add('active');
      state.currentView = 'files';
      showMainViews();
      loadViewData('files');
    });
  }
  var siEmptyUploadBtn = document.getElementById('si-empty-upload-btn');
  if (siEmptyUploadBtn) {
    siEmptyUploadBtn.addEventListener('click', function() {
      var fileInput = document.getElementById('file-input');
      if (fileInput) fileInput.click();
    });
  }
});

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
  document.getElementById('shares-view').hidden = true;
  document.getElementById('vault-view').hidden = true;
  document.getElementById('vault-lock-screen').hidden = true;
  document.getElementById('activity-view').hidden = true;
  document.getElementById('storage-intel-view').hidden = true;
  document.getElementById('settings-view').hidden = true;
}

function showMainContent() {
  var mainPanel = document.querySelector('.main-panel');
  if (mainPanel) {
    var sections = mainPanel.querySelectorAll('.stats-row, .toolbar.panel, .content-panel, .status-strip');
    sections.forEach(function(s) { s.hidden = false; });
    var header = mainPanel.querySelector('.dashboard-header');
    if (header) header.hidden = false;
  }
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

function showSettingsView() {
  hideAllViews();
  document.getElementById('settings-view').hidden = false;
  // Update back button in settings toolbar
  const settingsBackBtn = document.getElementById('settings-back-btn');
  if (settingsBackBtn) {
    settingsBackBtn.textContent = '← Back';
    settingsBackBtn.onclick = () => {
      navigateToFiles();
    };
  }
  loadSettingsViewContent();
}

async function loadSettingsViewContent() {
  try {
    const status = await fetchJSON('/api/vault/status');
    // Update global vaultState to keep sidebar in sync
    vaultState.configured = status.configured;
    vaultState.unlocked = status.unlocked;
    updateVaultNav(); // Update sidebar immediately

    const container = document.getElementById('vault-security-content');
    if (!container) return;

    // Clear existing content
    container.innerHTML = '';

    if (!status.configured) {
      // Vault not set up
      container.innerHTML = `
        <div class="vault-status-section">
          <h3>Vault Security</h3>
          <p>Your Vault is not yet set up. Set up a PIN to protect your private files.</p>
          <button class="primary-btn" id="setup-vault-pin-btn">
            Set Up Vault PIN
          </button>
        </div>
      `;

      const setupBtn = container.querySelector('#setup-vault-pin-btn');
      if (setupBtn) {
        setupBtn.onclick = async () => {
          // Show PIN setup dialog
          const pin1 = await showPrompt('Set Vault PIN', 'Enter a new Vault PIN (6-128 characters)', 'New PIN');
          if (!pin1) return;

          const pin2 = await showPrompt('Confirm PIN', 'Re-enter your Vault PIN', 'Confirm PIN');
          if (!pin2) return;

          if (pin1 !== pin2) {
            showToast('PINs do not match', 'error');
            return;
          }

          try {
            await fetchJSON('/api/vault/pin', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ pin: pin1 })
            });
            showToast('Vault PIN set successfully', 'success');
            // Refresh the view to show updated state
            loadSettingsViewContent();
          } catch (error) {
            showToast(error.message || 'Failed to set PIN', 'error');
          }
        };
      }
    } else if (status.unlocked) {
      // Vault is unlocked
      container.innerHTML = `
        <div class="vault-status-section">
          <h3>Vault Security</h3>
          <p>Your Vault is currently unlocked and ready to use.</p>
          <div class="vault-actions">
            <button class="soft-btn" id="change-vault-pin-btn">
              Change PIN
            </button>
            <button class="danger-btn" id="lock-vault-btn">
              Lock Vault
            </button>
          </div>
        </div>
      `;

      const changePinBtn = container.querySelector('#change-vault-pin-btn');
      if (changePinBtn) {
        changePinBtn.onclick = async () => {
          // Show change PIN dialog
          const currentPin = await showPrompt('Current PIN', 'Enter your current Vault PIN', 'Current PIN');
          if (!currentPin) return;

          const newPin = await showPrompt('New PIN', 'Enter a new Vault PIN (6-128 characters)', 'New PIN');
          if (!newPin) return;

          const confirmPin = await showPrompt('Confirm PIN', 'Re-enter your new Vault PIN', 'Confirm PIN');
          if (!confirmPin) return;

          if (newPin !== confirmPin) {
            showToast('PINs do not match', 'error');
            return;
          }

          try {
            await fetchJSON('/api/vault/pin/change', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ current_pin: currentPin, new_pin: newPin })
            });
            showToast('Vault PIN changed successfully', 'success');
            // Refresh the view
            loadSettingsViewContent();
          } catch (error) {
            showToast(error.message || 'Failed to change PIN', 'error');
          }
        };
      }

      const lockVaultBtn = container.querySelector('#lock-vault-btn');
      if (lockVaultBtn) {
        lockVaultBtn.onclick = async () => {
          const ok = await showConfirm('Lock Vault?', 'This will immediately hide your private files.', 'Lock Vault');
          if (!ok) return;

          try {
            await fetchJSON('/api/vault/lock', { method: 'POST' });
            showToast('Vault locked', 'success');
            // Refresh the view
            loadSettingsViewContent();
          } catch (error) {
            showToast(error.message || 'Failed to lock Vault', 'error');
          }
        };
      }
    } else {
      // Vault is locked but configured
      container.innerHTML = `
        <div class="vault-status-section">
          <h3>Vault Security</h3>
          <p>Your Vault is configured but currently locked. Enter your PIN to unlock it.</p>
          <div class="vault-actions">
            <button class="soft-btn" id="unlock-vault-btn">
              Unlock Vault
            </button>
            <button class="soft-btn" id="change-vault-pin-locked-btn">
              Change PIN
            </button>
          </div>
        </div>
      `;

      const unlockVaultBtn = container.querySelector('#unlock-vault-btn');
      if (unlockVaultBtn) {
        unlockVaultBtn.onclick = async () => {
          const pin = await showPrompt('Vault PIN', 'Enter your Vault PIN to unlock', 'PIN');
          if (!pin) return;

          try {
            await fetchJSON('/api/vault/unlock', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ pin: pin })
            });
            showToast('Vault unlocked successfully', 'success');
            // Refresh the view
            loadSettingsViewContent();
          } catch (error) {
            showToast(error.message || 'Invalid PIN', 'error');
          }
        };
      }

      const changePinBtn = container.querySelector('#change-vault-pin-locked-btn');
      if (changePinBtn) {
        changePinBtn.onclick = async () => {
          // Show change PIN dialog (requires current PIN)
          const currentPin = await showPrompt('Current PIN', 'Enter your current Vault PIN', 'Current PIN');
          if (!currentPin) return;

          const newPin = await showPrompt('New PIN', 'Enter a new Vault PIN (6-128 characters)', 'New PIN');
          if (!newPin) return;

          const confirmPin = await showPrompt('Confirm PIN', 'Re-enter your new Vault PIN', 'Confirm PIN');
          if (!confirmPin) return;

          if (newPin !== confirmPin) {
            showToast('PINs do not match', 'error');
            return;
          }

          try {
            await fetchJSON('/api/vault/pin/change', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ current_pin: currentPin, new_pin: newPin })
            });
            showToast('Vault PIN changed successfully', 'success');
            // Refresh the view
            loadSettingsViewContent();
          } catch (error) {
            showToast(error.message || 'Failed to change PIN', 'error');
          }
        };
      }
    }
  } catch (error) {
    console.error('Failed to load vault status:', error);
    const container = document.getElementById('vault-security-content');
    if (container) {
      container.innerHTML = `
        <div class="vault-status-section">
          <h3>Vault Security</h3>
          <p>Unable to load Vault status. Please try again later.</p>
        </div>
      `;
    }
  }
}

function showVaultNotConfigured() {
  document.getElementById('vault-view').hidden = true;
  var lockScreen = document.getElementById('vault-lock-screen');
  lockScreen.hidden = false;
  var card = lockScreen.querySelector('.vault-lock-card');
  if (card) {
    card.innerHTML = '<div class="vault-lock-icon">&#128274;</div>' +
      '<h2 class="vault-lock-title">Vault Not Set Up</h2>' +
      '<p class="vault-lock-desc">Set up your Vault PIN to protect your private files.</p>' +
      '<div class="vault-actions">' +
      '<button class="primary-btn" id="setup-vault-btn">Set Up Vault</button>' +
      '<button class="soft-btn" id="vault-back-to-drive-btn">← Back to My Drive</button>' +
      '</div>';
  }

  // Add event listeners for the buttons
  const setupBtn = lockScreen.querySelector('#setup-vault-btn');
  if (setupBtn) {
    setupBtn.onclick = () => {
      // Navigate to Settings view to set up PIN
      document.querySelector('[data-view="settings"]').click();
    };
  }

  const backToDriveBtn = lockScreen.querySelector('#vault-back-to-drive-btn');
  if (backToDriveBtn) {
    backToDriveBtn.onclick = () => {
      navigateToFiles();
    };
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
