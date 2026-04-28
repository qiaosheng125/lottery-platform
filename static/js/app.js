const DEVICE_ID_INVALID_MESSAGE = '\u8bbe\u5907\u6807\u8bc6\u53ea\u80fd\u5305\u542b\u5b57\u6bcd\u3001\u6570\u5b57\u3001\u8fde\u5b57\u7b26\u548c\u4e0b\u5212\u7ebf\uff0c\u4e14\u957f\u5ea6\u4e0d\u80fd\u8d85\u8fc7 20\u3002';

function getOrCreateDeviceId() {
  return localStorage.getItem('lottery_device_id') || '';
}

function saveDeviceId(id) {
  localStorage.setItem('lottery_device_id', id);
}

function isValidDeviceId(id) {
  return !!id && id.length <= 20 && /^[A-Za-z0-9_-]+$/.test(id);
}

function clearStoredDevice() {
  localStorage.removeItem('lottery_device_id');
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

function refreshDeviceIdDisplays() {
  const deviceId = getOrCreateDeviceId();
  const shortDisplay = deviceId ? deviceId.substring(0, 8) + (deviceId.length > 8 ? '...' : '') : '';
  const fullDisplay = deviceId || '\u672a\u8bbe\u7f6e';

  ['device-name-badge', 'device-name-badge-b'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = shortDisplay ? '\u8bbe\u5907 ' + shortDisplay : '';
  });

  const currentDisplay = document.getElementById('current-device-id-display');
  if (currentDisplay) currentDisplay.textContent = fullDisplay;
}

async function registerDeviceAndCheckName() {
  const deviceId = getOrCreateDeviceId();
  refreshDeviceIdDisplays();
  if (!deviceId || !isValidDeviceId(deviceId)) {
    clearStoredDevice();
    refreshDeviceIdDisplays();
    showDeviceIdPrompt(deviceId ? DEVICE_ID_INVALID_MESSAGE : '');
    return;
  }

  try {
    const res = await fetch('/api/device/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_id: deviceId,
        client_info: { client_type: 'web' },
      }),
    });
    const data = await res.json();
    if (data && data.success && data.device) {
      return;
    }
    if (data && data.error) {
      showToast(data.error, 'warning');
    }
  } catch (e) {
  }
}

function showDeviceIdPrompt(message = '', mode = 'create') {
  const existing = document.getElementById('device-id-modal');
  if (existing) existing.remove();

  const currentId = getOrCreateDeviceId();
  const isEdit = mode === 'edit';
  const title = isEdit ? '\u4fee\u6539\u8bbe\u5907ID' : '\u9996\u6b21\u4f7f\u7528\uff1a\u8bbe\u7f6e\u63a5\u5355\u8bbe\u5907\u6807\u8bc6';
  const intro = isEdit
    ? '\u8bf7\u8f93\u5165\u65b0\u7684\u8bbe\u5907ID\u3002\u82e5\u5f53\u524d\u8bbe\u5907\u8fd8\u6709\u5904\u7406\u4e2d\u7684\u7968\uff0c\u9700\u5148\u5b8c\u6210\u6216\u505c\u6b62\u63a5\u5355\u540e\u518d\u4fee\u6539\u3002'
    : '\u8bf7\u8f93\u5165\u8bbe\u5907\u6807\u8bc6\uff08\u5982 D01\uff09\u3002\u7f51\u9875\u7aef\u540e\u7eed\u5c06\u53ea\u4f7f\u7528\u8fd9\u4e00\u4e2a\u503c\uff0c\u4e0d\u518d\u5355\u72ec\u8981\u6c42\u8bbe\u7f6e\u8bbe\u5907\u540d\u3002';
  const primaryText = isEdit ? '\u786e\u8ba4\u4fee\u6539' : '\u786e\u8ba4\u4fdd\u5b58';

  const modal = document.createElement('div');
  modal.id = 'device-id-modal';
  modal.dataset.mode = mode;
  modal.dataset.oldDeviceId = currentId;
  modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `
    <div style="background:#fff;border-radius:8px;padding:24px;width:340px;max-width:90vw;">
      <h5 class="mb-3"><i class="bi bi-cpu"></i> ${title}</h5>
      <p class="text-muted small mb-3">${intro}</p>
      ${message ? `<div class="alert alert-warning py-2 small">${escapeHtml(message)}</div>` : ''}
      <input type="text" id="device-id-input" class="form-control mb-3"
             placeholder="\u8bf7\u8f93\u5165\u8bbe\u5907\u6807\u8bc6" maxlength="20" value="${escapeHtml(currentId)}" autofocus>
      <div class="d-flex gap-2">
        <button class="btn btn-secondary" onclick="closeDeviceIdModal()">\u53d6\u6d88</button>
        <button class="btn btn-primary flex-grow-1" onclick="submitDeviceId()">${primaryText}</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const input = document.getElementById('device-id-input');
  input.focus();
  input.select();
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') submitDeviceId();
  });
}

function closeDeviceIdModal() {
  const modal = document.getElementById('device-id-modal');
  if (modal) modal.remove();
}

async function submitDeviceId() {
  const modal = document.getElementById('device-id-modal');
  const input = document.getElementById('device-id-input');
  const id = input ? input.value.trim() : '';
  const oldId = modal ? (modal.dataset.oldDeviceId || '') : getOrCreateDeviceId();

  if (!id) {
    input && input.classList.add('is-invalid');
    return;
  }
  if (!isValidDeviceId(id)) {
    input && input.classList.add('is-invalid');
    showToast(DEVICE_ID_INVALID_MESSAGE, 'warning');
    return;
  }

  try {
    const res = await fetch('/api/device/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_device_id: oldId || undefined,
        new_device_id: id,
        client_info: { client_type: 'web' },
      }),
    });
    const data = await res.json();
    if (!res.ok || !data || data.success === false) {
      throw new Error((data && data.error) || '\u4fee\u6539\u8bbe\u5907ID\u5931\u8d25');
    }

    saveDeviceId(id);
    refreshDeviceIdDisplays();
    closeDeviceIdModal();
    showToast(oldId && oldId !== id ? '\u8bbe\u5907ID\u5df2\u4fee\u6539' : '\u8bbe\u5907ID\u5df2\u4fdd\u5b58', 'success');
    window.location.reload();
  } catch (e) {
    showToast(e.message || '\u4fee\u6539\u8bbe\u5907ID\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5', 'danger');
  }
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container') || (() => {
    const el = document.createElement('div');
    el.id = 'toast-container';
    el.className = 'position-fixed bottom-0 end-0 p-3';
    el.style.zIndex = 9999;
    document.body.appendChild(el);
    return el;
  })();

  const toast = document.createElement('div');
  toast.className = `toast align-items-center text-bg-${type} border-0 show`;
  toast.role = 'alert';
  toast.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${escapeHtml(message)}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`;
  container.appendChild(toast);
  setTimeout(() => { toast.remove(); }, 3500);
}

const style = document.createElement('style');
style.textContent = `.btn-xs { padding: 0.1rem 0.4rem; font-size: 0.75rem; }`;
document.head.appendChild(style);
