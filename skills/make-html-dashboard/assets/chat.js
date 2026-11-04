/* ============================================================
   Dashboard chat widget.
   The page injects window.DASHBOARD_CHAT = { endpoint, suggestions }
   when the dashboard payload contains a `chat` object.
   ============================================================ */
(function () {
  'use strict';

  var cfg = window.DASHBOARD_CHAT || {};
  var button = document.getElementById('chatbtn');
  var panel = document.getElementById('chatpanel');
  if (!button || !panel) return;

  var log = document.getElementById('chat-log');
  var form = document.getElementById('chat-form');
  var input = document.getElementById('chat-input');
  var send = document.getElementById('chat-send');
  var close = document.getElementById('chat-close');
  var expand = document.getElementById('chat-expand');
  var foot = document.getElementById('chat-foot');
  var chips = document.getElementById('chat-chips');
  var history = [];
  var busy = false;

  function endpointCandidates() {
    var list = [];
    var configured = cfg.endpoint || '/api/chat';
    var isAbsolute = /^https?:\/\//i.test(configured);
    if (isAbsolute) {
      list.push(configured);
    } else if (location.protocol !== 'file:') {
      list.push(configured);
    }
    var host = location.hostname || '127.0.0.1';
    var fallback = cfg.fallbackEndpoint || ('http://' + host + ':5000/api/chat');
    if (list.indexOf(fallback) === -1) list.push(fallback);
    if (host !== '127.0.0.1' && list.indexOf('http://127.0.0.1:5000/api/chat') === -1) {
      list.push('http://127.0.0.1:5000/api/chat');
    }
    return list;
  }

  function postQuestion(question, prior) {
    var candidates = endpointCandidates();
    var index = 0;
    var lastError = null;

    function attempt() {
      var url = candidates[index++];
      return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question, history: prior })
      }).then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          if (response.ok) return body;
          var error = new Error(body.error || ('Request failed (' + response.status + ')'));
          error.status = response.status;
          error.endpoint = url;
          // 404/405/501 usually mean the page is served by a static preview,
          // not the dashboard Flask server. Try the localhost fallback.
          if ([404, 405, 501].indexOf(response.status) !== -1 && index < candidates.length) {
            return attempt();
          }
          throw error;
        });
      }).catch(function (error) {
        if (error && error.status) throw error;
        lastError = error;
        if (index < candidates.length) return attempt();
        throw lastError || error;
      });
    }

    return attempt();
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* Small, safe Markdown subset: code fences, inline code, bold, bullets. */
  function render(text) {
    var raw = String(text == null ? '' : text);
    var parts = raw.split(/```/);
    return parts.map(function (part, index) {
      if (index % 2 === 1) {
        var code = part.replace(/^[a-zA-Z0-9_-]*\n/, '').replace(/\n$/, '');
        return '<pre><code>' + escapeHtml(code) + '</code></pre>';
      }
      var safe = escapeHtml(part);
      safe = safe.replace(/`([^`\n]+)`/g, '<code>$1</code>');
      safe = safe.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
      safe = safe.replace(/(^|\n)[-*]\s+(.+)/g, '$1<li>$2</li>');
      if (safe.indexOf('<li>') !== -1) {
        safe = safe.replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>');
      }
      safe = safe.replace(/\n/g, '<br>');
      return safe;
    }).join('');
  }

  function addMessage(role, text, isError) {
    var message = document.createElement('div');
    message.className = 'chat-msg ' + role + (isError ? ' error' : '');
    message.innerHTML = render(text);
    log.appendChild(message);
    log.scrollTop = log.scrollHeight;
    return message;
  }

  function addTyping() {
    var message = document.createElement('div');
    message.className = 'chat-msg bot chat-typing';
    message.innerHTML = '<span></span><span></span><span></span>';
    log.appendChild(message);
    log.scrollTop = log.scrollHeight;
    return message;
  }

  function setBusy(value) {
    busy = value;
    send.disabled = value;
    input.disabled = value;
    send.textContent = value ? '…' : 'Send';
  }

  var WIDE_KEY = 'dashboard-chat-wide';

  function setWide(wide) {
    panel.classList.toggle('chat-wide', wide);
    if (expand) {
      expand.setAttribute('aria-pressed', String(wide));
      expand.setAttribute('aria-label', wide
        ? 'Restore chat width'
        : 'Expand chat to two thirds of the screen');
      expand.title = wide ? 'Restore chat width' : 'Expand to 2/3 width';
    }
    try { localStorage.setItem(WIDE_KEY, wide ? '1' : '0'); } catch (e) { /* ignore */ }
  }

  function openPanel(open) {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    if (open) {
      resizeInput();
      setTimeout(function () { input.focus(); }, 30);
    }
  }

  function resizeInput() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 104) + 'px';
  }

  function ask(question) {
    var text = String(question || '').trim();
    if (!text || busy) return;

    var prior = history.slice(-8);
    addMessage('user', text);
    history.push({ role: 'user', content: text });
    input.value = '';
    resizeInput();
    setBusy(true);
    var typing = addTyping();

    postQuestion(text, prior)
      .then(function (body) {
        if (typing.parentNode) typing.parentNode.removeChild(typing);
        var answer = body.answer || 'The model returned no answer.';
        addMessage('bot', answer);
        history.push({ role: 'assistant', content: answer });
        if (body.model && foot) {
          foot.textContent = 'Model: ' + body.model + ' · snapshot data only';
        }
      })
      .catch(function (error) {
        if (typing.parentNode) typing.parentNode.removeChild(typing);
        var detail = error.message || 'Unknown network error';
        if (error.status === 405 || error.status === 404 || error.status === 501) {
          detail = 'This page is not being served by the dashboard server (HTTP ' + error.status + '). '
            + 'Run `uv run src/server.py --open` and open http://127.0.0.1:5000/ — or keep the server running on port 5000 while using your preview server.';
        } else if (!error.status) {
          detail = 'No chat endpoint answered. Start the local server with `uv run src/server.py --open` (port 5000), then try again.';
        }
        addMessage('bot', 'Could not reach the dashboard model. ' + detail, true);
      })
      .then(function () {
        setBusy(false);
        input.focus();
      });
  }

  button.addEventListener('click', function () {
    openPanel(panel.hidden);
  });
  close.addEventListener('click', function () {
    openPanel(false);
    button.focus();
  });
  if (expand) {
    expand.addEventListener('click', function () {
      setWide(!panel.classList.contains('chat-wide'));
    });
    try {
      if (localStorage.getItem(WIDE_KEY) === '1') setWide(true);
    } catch (e) { /* storage unavailable */ }
  }
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !panel.hidden) {
      openPanel(false);
      button.focus();
    }
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    ask(input.value);
  });
  input.addEventListener('input', resizeInput);
  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      ask(input.value);
    }
  });

  if (chips) {
    chips.addEventListener('click', function (event) {
      var chip = event.target.closest('.chat-chip');
      if (chip) ask(chip.textContent);
    });
  }

  resizeInput();
})();
