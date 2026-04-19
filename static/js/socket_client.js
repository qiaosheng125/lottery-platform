// Socket.IO 客户端连接和事件处理
(function() {
  // Only connect if socket.io is available
  if (typeof io === 'undefined') return;

  function submitLogout() {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/auth/logout';
    form.style.display = 'none';
    document.body.appendChild(form);
    form.submit();
  }

  const socket = io({ transports: ['websocket', 'polling'] });

  socket.on('connect', () => {
    console.log('Socket connected:', socket.id);
  });

  socket.on('disconnect', () => {
    console.log('Socket disconnected');
  });

  socket.on('pool_updated', (data) => {
    // Update pool display if element exists
    const el = document.getElementById('pool-pending-count');
    if (el && data.total_pending !== undefined) {
      el.textContent = data.total_pending;
    }
    // Dispatch custom event for Vue components
    window.dispatchEvent(new CustomEvent('pool_updated', { detail: data }));
  });

  socket.on('force_logout', (data) => {
    alert(data.reason || '您已被强制下线，请重新登录');
    submitLogout();
  });

  socket.on('announcement', (data) => {
    const bar = document.getElementById('announcement-bar');
    const text = document.getElementById('announcement-text');
    if (bar && text && data.content) {
      text.textContent = data.content;
      bar.classList.remove('d-none');
    }
    window.dispatchEvent(new CustomEvent('announcement', { detail: data }));
  });

  socket.on('pool_disabled', (data) => {
    showToast(data.message || '票池已关闭', 'warning');
    window.dispatchEvent(new CustomEvent('pool_disabled', { detail: data }));
  });

  socket.on('pool_enabled', (data) => {
    showToast(data.message || '票池已开启', 'success');
    window.dispatchEvent(new CustomEvent('pool_enabled', { detail: data }));
  });

  socket.on('file_revoked', (data) => {
    showToast(`文件已撤回，${data.revoked_count} 张票已取消`, 'warning');
    window.dispatchEvent(new CustomEvent('file_revoked', { detail: data }));
  });

  socket.on('file_uploaded', (data) => {
    window.dispatchEvent(new CustomEvent('file_uploaded', { detail: data }));
  });

  socket.on('winning_calc_done', (data) => {
    showToast(`期号 ${data.period} 中奖计算完成，共 ${data.winning_count} 张中奖`, 'success');
  });

  window._socket = socket;
})();
