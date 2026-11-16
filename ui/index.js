// The Assistant's screens, as plain custom elements: no framework and no build
// step, the same way as the template plugin's (core/plugins/hc-plugin-template/ui).
// The plugin serves this folder as it is.
//
//   hc-mcp-chat      (app.assistant)  host, mode. The "Ask homeCore" panel:
//                    the app gives it a 440 px side panel (`mode` 'panel') or,
//                    on a phone, a whole page (`mode` 'page') and an "Ask"
//                    button; everything inside is this element's. It asks to
//                    be closed with a `close` event.
//   hc-mcp-settings  (plugin.page)    host. Settings > Plugins > Assistant.
//
// The chat talks to the plugin's `chat` action through `host.stream`, and
// answers its confirm cards with `host.respond`. What arrives on the stream is
// listed in docs/chat-events.md. Colors are the app's own CSS variables, so
// light and dark both follow the app.

const ICON = {
	history:
		'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>',
	close:
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
	back: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>',
	send: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
	stop: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
	check:
		'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
	cross:
		'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
	trash:
		'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>'
};

/** Text made safe to put in markup. */
function esc(s) {
	return String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/** The model's text as paragraphs and lists, with **bold**. Nothing else. */
function prose(text) {
	const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
	return String(text ?? '')
		.trim()
		.split(/\n{2,}/)
		.map((block) => {
			const lines = block.split('\n');
			if (lines.every((l) => /^\s*[-*] /.test(l))) {
				return `<ul>${lines.map((l) => `<li>${inline(l.replace(/^\s*[-*] /, ''))}</li>`).join('')}</ul>`;
			}
			return `<p>${lines.map(inline).join('<br>')}</p>`;
		})
		.join('');
}

function when(ts) {
	const d = new Date(ts * 1000);
	const today = new Date();
	if (d.toDateString() === today.toDateString()) {
		return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
	}
	return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

const ROLE_WORDS = {
	admin: 'an admin',
	user: 'a user',
	household_member: 'a household member',
	read_only: 'a read only account',
	observer: 'an observer',
	device_operator: 'a device operator',
	rule_editor: 'a rule editor',
	service_operator: 'a service account'
};

/** Shared look: the app's variables, so dark mode follows the app. */
const CHAT_CSS = `
:host { display: flex; flex-direction: column; height: 100%; min-height: 0;
	background: var(--sheet, #fbfaf6); color: var(--ink, #1e2126);
	font-family: var(--font, system-ui, sans-serif); }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
button { font: inherit; cursor: pointer; }
button:focus-visible, textarea:focus-visible, a:focus-visible { outline: 2px solid var(--accent, #9a4a07); outline-offset: 2px; }
.head { height: 56px; flex: none; display: flex; align-items: center; gap: 8px;
	padding: 0 12px 0 20px; border-bottom: 1px solid var(--line, #e2dccf); }
.head b { flex: 1; font-size: 16px; }
.narrow .head { padding: 0 8px; gap: 6px; }
.narrow .head b { font-size: 17px; }
.pill { height: 34px; padding: 0 12px; border-radius: 17px; border: 1px solid var(--line, #e2dccf);
	background: var(--surface, #fff); color: var(--ink, #1e2126); font-size: 14px; font-weight: 600; }
.round { width: 34px; height: 34px; border-radius: 17px; border: 1px solid var(--line, #e2dccf);
	background: var(--surface, #fff); color: var(--ink-muted, #5d6470);
	display: inline-flex; align-items: center; justify-content: center; padding: 0; }
.bare { border: none; background: transparent; }
.narrow .back { width: 44px; height: 44px; border-radius: 22px; color: var(--ink, #1e2126); }
.body { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.narrow .body { padding: 16px; gap: 12px; }
.me { align-self: flex-end; max-width: 300px; background: var(--nav-on, #e4ddcd);
	border-radius: 18px 18px 4px 18px; padding: 10px 14px; font-size: 15px; white-space: pre-wrap; overflow-wrap: anywhere; }
.reply { display: flex; flex-direction: column; gap: 10px; }
.reply p { margin: 0; font-size: 15px; line-height: 1.5; }
.reply ul { margin: 0; padding-left: 20px; font-size: 15px; line-height: 1.5; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 10px; border-radius: 13px;
	background: var(--surface-2, #eeeae0); color: var(--ink-muted, #5d6470); font-size: 12px; font-weight: 600; }
.chip.failed { color: var(--alert, #b42318); }
.spin { width: 10px; height: 10px; border-radius: 50%; border: 2px solid currentColor; border-right-color: transparent;
	animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
.card { background: var(--surface, #fff); border: 1px solid var(--card-line, #e9e3d6); border-radius: var(--radius, 14px); overflow: hidden; }
.card h3 { margin: 0; padding: 10px 14px 0; font-size: 13px; font-weight: 700; color: var(--ink-muted, #5d6470); }
.row { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-top: 1px solid var(--card-line, #e9e3d6); }
.card h3 + .row { border-top: none; }
.row .what { flex: 1; font-size: 14px; }
.row .state { color: var(--ink-muted, #5d6470); font-size: 13px; font-weight: 700; }
.row .state.lit { color: var(--lit-ink, #8a4206); }
.confirm { background: var(--surface, #fff); border: 2px solid var(--accent, #9a4a07); border-radius: var(--radius, 14px);
	padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.confirm.rule { padding: 0; overflow: hidden; gap: 0; }
.confirm .top { padding: 12px 14px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid var(--card-line, #e9e3d6); }
.confirm .top b { flex: 1; }
.badge { height: 22px; padding: 0 8px; border-radius: 11px; background: var(--lit-bg, #fbe3bf); color: var(--lit-ink, #8a4206);
	font-size: 12px; font-weight: 700; display: inline-flex; align-items: center; }
.confirm b.title { font-size: 14px; }
.confirm .detail { color: var(--ink-muted, #5d6470); font-size: 14px; overflow-wrap: anywhere; }
.confirm dl { margin: 0; padding: 12px 14px; display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 8px 10px; font-size: 14px; }
.confirm dt { color: var(--ink-muted, #5d6470); font-weight: 700; }
.confirm dd { margin: 0; }
.confirm details { padding: 0 14px 10px; font-size: 13px; color: var(--ink-muted, #5d6470); }
.confirm pre { margin: 6px 0 0; padding: 8px 10px; border-radius: 10px; background: var(--surface-2, #eeeae0);
	font-family: var(--font-num, monospace); font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow: auto; }
.buttons { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
.confirm.rule .buttons { padding: 0 14px 14px; }
.btn { height: 36px; padding: 0 14px; border-radius: 18px; border: 1px solid var(--line, #e2dccf);
	background: var(--surface, #fff); color: var(--ink, #1e2126); font-weight: 700; }
.btn.primary { border: none; background: var(--accent, #9a4a07); color: var(--accent-ink, #fff); padding: 0 16px; }
.btn.danger { border: none; background: var(--alert, #b42318); color: var(--alert-ink, #fff); padding: 0 16px; }
.btn:disabled { opacity: 0.6; cursor: default; }
.link { display: inline-flex; align-items: center; height: 36px; padding: 0 12px; color: var(--accent, #9a4a07);
	font-weight: 700; text-decoration: none; background: none; border: none; }
.quiet { margin: 0; color: var(--ink-muted, #5d6470); font-size: 13px; }
.decided { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 14px; color: var(--ink-muted, #5d6470); }
.decided.done { color: var(--good-ink, var(--ink, #1e2126)); }
.decided.failed { color: var(--alert, #b42318); }
.decided .link { height: auto; padding: 0; }
.notice { padding: 10px 14px; border-radius: var(--radius, 14px); background: var(--surface-2, #eeeae0);
	color: var(--ink-muted, #5d6470); font-size: 14px; line-height: 1.45; }
.notice.bad { background: var(--alert-bg, #fce9e6); color: var(--ink, #1e2126); border: 1px solid var(--alert-line, #f2c2bb); }
.suggest { display: flex; flex-wrap: wrap; gap: 8px; }
.suggest .btn { font-weight: 600; font-size: 14px; }
.empty { margin: auto 0; display: flex; flex-direction: column; gap: 10px; color: var(--ink-muted, #5d6470); font-size: 15px; line-height: 1.5; }
.empty b { color: var(--ink, #1e2126); font-size: 17px; }
.who { margin-top: auto; padding: 12px 14px; border-radius: var(--radius, 14px); background: var(--surface-2, #eeeae0);
	color: var(--ink-muted, #5d6470); font-size: 13px; line-height: 1.45; }
.typing { display: inline-flex; gap: 4px; padding: 4px 0; }
.typing i { width: 6px; height: 6px; border-radius: 3px; background: var(--ink-muted, #5d6470); opacity: 0.5; animation: blink 1.2s infinite; }
.typing i:nth-child(2) { animation-delay: 0.2s; } .typing i:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .typing i { animation: none; } }
form { flex: none; padding: 12px 16px 16px; border-top: 1px solid var(--line, #e2dccf); display: flex; gap: 8px; align-items: flex-end; margin: 0; }
.narrow form { padding: 10px 12px 24px; }
.sr { position: absolute; left: -9999px; }
textarea { flex: 1; resize: none; min-height: 44px; max-height: 160px; padding: 11px 14px; border-radius: 22px;
	border: 1px solid var(--line, #e2dccf); background: var(--surface, #fff); font: inherit; font-size: 15px; color: var(--ink, #1e2126); }
.narrow textarea { font-size: 16px; }
.go { width: 44px; height: 44px; flex: none; border-radius: 22px; border: none; background: var(--accent, #9a4a07);
	color: var(--accent-ink, #fff); display: inline-flex; align-items: center; justify-content: center; padding: 0; }
.go:disabled { opacity: 0.5; cursor: default; }
.list { display: flex; flex-direction: column; }
.past { display: flex; align-items: center; gap: 8px; border-bottom: 1px solid var(--card-line, #e9e3d6); }
.past button.open { flex: 1; text-align: left; background: none; border: none; color: inherit; padding: 12px 4px; display: flex; flex-direction: column; gap: 2px; }
.past .t { font-size: 15px; font-weight: 600; }
.past .d { font-size: 13px; color: var(--ink-muted, #5d6470); }
`;

/**
 * The chat. Holds the open conversation (`turns`, as the plugin stores them),
 * the reply being written (`live`), and a confirm card waiting for an answer.
 */
class McpChat extends HTMLElement {
	#host;
	#view = 'chat'; // 'chat' | 'past'
	#chatId = null;
	#turns = [];
	#live = null;
	#confirm = null; // { requestId, id, preview, choices, sent }
	#run = null; // what host.stream returned
	#requestId = null;
	#queued = null; // text sent while a confirm card waited
	#past = null;
	#frame = 0;
	#resize;
	#mode = null;

	constructor() {
		super();
		this.attachShadow({ mode: 'open' });
	}

	set host(h) {
		if (this.#host === h) return;
		this.#host = h;
		const own = new CSSStyleSheet();
		own.replaceSync(CHAT_CSS);
		this.shadowRoot.adoptedStyleSheets = h?.theme?.sheet ? [h.theme.sheet, own] : [own];
		this.#build();
	}
	get host() {
		return this.#host;
	}

	/** 'panel' beside the page, or 'page' (a phone's whole screen). */
	set mode(m) {
		this.#mode = m;
		this.#narrow();
	}
	get mode() {
		return this.#mode;
	}

	connectedCallback() {
		// A phone gets the panel as a whole page: a back arrow instead of the
		// close button, and roomier touch targets.
		this.#resize = new ResizeObserver(() => this.#narrow());
		this.#resize.observe(this);
	}

	disconnectedCallback() {
		this.#resize?.disconnect();
	}

	/** Who is asking, from the host: `me` (app 0.1.x) or `user` (newer). */
	#me() {
		const h = this.#host;
		const role = h?.user?.role ?? h?.me?.role ?? 'user';
		const can = (scope) => (typeof h?.me?.can === 'function' ? h.me.can(scope) : true);
		return { role, can, isAdmin: h?.me?.isAdmin ?? role === 'admin' };
	}

	// ── the frame: header, body, composer ───────────────────────────────

	#build() {
		if (!this.#host) return;
		const me = this.#me();
		const placeholder = me.can('automations:write')
			? 'Ask about the house, or what to automate'
			: 'Ask about the house';
		this.shadowRoot.innerHTML = `
			<div class="frame" style="display:flex;flex-direction:column;height:100%;min-height:0">
				<div class="head">
					<button type="button" class="round bare back" data-do="close" aria-label="Back" hidden>${ICON.back}</button>
					<b id="title">Ask homeCore</b>
					<button type="button" class="pill" data-do="new">New chat</button>
					<button type="button" class="round past-btn" data-do="past" aria-label="Past chats">${ICON.history}</button>
					<button type="button" class="round bare x" data-do="close" aria-label="Close">${ICON.close}</button>
				</div>
				<div class="body" aria-live="polite"></div>
				<form>
					<label style="flex:1;display:flex"><span class="sr">Message</span>
						<textarea rows="1" placeholder="${esc(placeholder)}"></textarea>
					</label>
					<button type="submit" class="go" aria-label="Send">${ICON.send}</button>
				</form>
			</div>`;
		const root = this.shadowRoot;
		root.addEventListener('click', (e) => this.#click(e));
		const ta = root.querySelector('textarea');
		ta.addEventListener('input', () => this.#grow(ta));
		ta.addEventListener('keydown', (e) => {
			if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
				e.preventDefault();
				this.#submit();
			}
		});
		root.querySelector('form').addEventListener('submit', (e) => {
			e.preventDefault();
			if (this.#run && !this.#confirm) this.#stop();
			else this.#submit();
		});
		this.#narrow();
		this.#draw();
	}

	#narrow() {
		const narrow = this.#mode ? this.#mode === 'page' : this.clientWidth > 0 && this.clientWidth < 480;
		const frame = this.shadowRoot.querySelector('.frame');
		if (!frame) return;
		frame.classList.toggle('narrow', narrow);
		frame.querySelector('.back').hidden = !narrow;
		frame.querySelector('.x').hidden = narrow;
		frame.querySelector('.past-btn').hidden = false;
	}

	#grow(ta) {
		ta.style.height = 'auto';
		ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
	}

	#click(e) {
		const el = e.target.closest('[data-do]');
		if (!el) return;
		const what = el.dataset.do;
		if (what === 'close') this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
		else if (what === 'new') this.#newChat();
		else if (what === 'past') this.#openPast();
		else if (what === 'back-chat') {
			this.#view = 'chat';
			this.#draw();
		} else if (what === 'open') this.#openChat(el.dataset.id);
		else if (what === 'delete') this.#deleteChat(el.dataset.id);
		else if (what === 'choose') this.#choose(el.dataset.choice);
		else if (what === 'say') this.#send(el.dataset.text);
		else if (what === 'editor') this.#host.ui?.navigate?.(`/settings/automations/${encodeURIComponent(el.dataset.id)}`);
	}

	// ── chats ────────────────────────────────────────────────────────────

	#newChat() {
		if (this.#run) this.#stop();
		this.#chatId = null;
		this.#turns = [];
		this.#live = null;
		this.#confirm = null;
		this.#view = 'chat';
		this.#draw();
		this.shadowRoot.querySelector('textarea')?.focus();
	}

	async #openPast() {
		this.#view = 'past';
		this.#past = null;
		this.#draw();
		const res = await this.#host.action('chats');
		this.#past = res.ok ? (res.data.chats ?? []) : { error: res.ok ? res.data.error : res.error };
		this.#draw();
	}

	async #openChat(id) {
		const res = await this.#host.action('chat_get', { chat_id: id });
		if (!res.ok || !res.data.chat) return;
		if (this.#run) this.#stop();
		this.#chatId = id;
		this.#turns = res.data.chat.turns ?? [];
		this.#live = null;
		this.#confirm = null;
		this.#view = 'chat';
		this.#draw(true);
	}

	async #deleteChat(id) {
		await this.#host.action('chat_delete', { chat_id: id });
		if (id === this.#chatId) this.#newChat();
		this.#openPast();
	}

	// ── sending and the stream ───────────────────────────────────────────

	#submit() {
		const ta = this.shadowRoot.querySelector('textarea');
		const text = ta.value.trim();
		if (!text) return;
		ta.value = '';
		this.#grow(ta);
		this.#send(text);
	}

	#send(text) {
		if (!text) return;
		// A confirm card is waiting: the reply is the answer to it ("make it
		// 10 minutes"), so say no to the card, then send once the reply ends.
		if (this.#run && this.#confirm) {
			this.#queued = text;
			this.#answer('cancel', 'replied');
			return;
		}
		if (this.#run) return;
		if (typeof this.#host.stream !== 'function') {
			this.#turns.push({ role: 'user', text });
			this.#turns.push({ role: 'assistant', parts: [{ id: 'old', kind: 'notice', bad: true,
				text: 'The chat needs a newer homeCore app.' }] });
			this.#draw(true);
			return;
		}
		this.#turns.push({ role: 'user', text });
		this.#live = { role: 'assistant', parts: [] };
		const params = { text };
		if (this.#chatId) params.chat_id = this.#chatId;
		const units = this.#host.units?.temperature;
		if (units) params.units = units;
		const run = this.#host.stream('chat', params, (ev) => this.#event(ev));
		this.#run = run;
		if (run?.requestId) this.#requestId = run.requestId;
		// The terminal event arrives through onEvent as well; this is only
		// for a stream that ended without one (and never for a later reply).
		const ended = (end) => {
			if (this.#run === run) this.#end(end);
		};
		Promise.resolve(run?.done)
			.then((end) => ended(end && end.stage ? end : { stage: 'error', message: 'The reply stopped.' }))
			.catch((err) => ended({ stage: 'error', message: String(err?.message ?? err) }));
		this.#draw(true);
	}

	#stop() {
		try {
			this.#run?.cancel();
		} catch {
			/* already over */
		}
	}

	#event(ev) {
		if (!ev || typeof ev !== 'object' || !this.#live) return;
		if (ev.request_id) this.#requestId = ev.request_id;
		const parts = this.#live.parts;
		const data = ev.data ?? {};
		switch (ev.stage) {
			case 'progress':
				if (data.kind === 'text') {
					let part = parts.find((p) => p.id === data.part);
					if (!part) {
						part = { id: data.part, kind: 'text', text: '' };
						parts.push(part);
					}
					part.text += data.delta ?? '';
				}
				break;
			case 'item': {
				const at = parts.findIndex((p) => p.id === data.id);
				if (ev.op === 'remove') {
					if (at >= 0) parts.splice(at, 1);
				} else if (at >= 0) parts[at] = { ...parts[at], ...data };
				else parts.push(data);
				if (data.kind === 'decided' && this.#confirm?.id === data.id) this.#confirm = null;
				break;
			}
			case 'awaiting_user':
				if (data.kind === 'confirm') {
					this.#confirm = { requestId: ev.request_id ?? this.#requestId, ...data, sent: false };
				}
				break;
			case 'complete':
			case 'error':
			case 'canceled':
			case 'timeout':
			case 'busy':
				this.#end(ev);
				return;
		}
		this.#schedule();
	}

	#end(ev) {
		if (!this.#live) return;
		const data = ev.data ?? {};
		if (ev.stage === 'complete' && data.turn) {
			this.#chatId = data.chat_id ?? this.#chatId;
			this.#live = data.turn;
		} else if (ev.stage === 'error') {
			if (!this.#live.parts.some((p) => p.kind === 'notice')) {
				this.#live.parts.push({ id: 'err', kind: 'notice', bad: true, text: ev.message || 'Something went wrong.' });
			}
		} else if (ev.stage === 'busy') {
			this.#live.parts.push({ id: 'end', kind: 'notice', text: 'The assistant is busy. Try again in a moment.' });
		} else if (ev.stage === 'timeout') {
			this.#live.parts.push({ id: 'end', kind: 'notice', text: 'That took too long and was stopped.' });
		} else if (ev.stage === 'canceled') {
			this.#live.parts.push({ id: 'end', kind: 'notice', text: 'Stopped.' });
		}
		this.#turns.push(this.#live);
		this.#live = null;
		this.#confirm = null;
		this.#run = null;
		this.#draw(true);
		if (this.#queued) {
			const next = this.#queued;
			this.#queued = null;
			this.#send(next);
		}
	}

	#choose(choice) {
		this.#answer(choice);
	}

	async #answer(choice, reason) {
		const c = this.#confirm;
		if (!c || c.sent) return;
		c.sent = true;
		this.#draw();
		const response = reason ? { choice, reason } : { choice };
		const res = await this.#host.respond?.(c.requestId, response);
		if (res && res.ok === false) {
			c.sent = false;
			this.#draw();
		}
	}

	// ── drawing ──────────────────────────────────────────────────────────

	#schedule() {
		if (this.#frame) return;
		this.#frame = requestAnimationFrame(() => {
			this.#frame = 0;
			this.#draw();
		});
	}

	#draw(toEnd = false) {
		const body = this.shadowRoot.querySelector('.body');
		if (!body) return;
		this.#narrow();
		const title = this.shadowRoot.getElementById('title');
		const go = this.shadowRoot.querySelector('.go');
		if (this.#view === 'past') {
			title.textContent = 'Past chats';
			body.innerHTML = this.#pastHtml();
			return;
		}
		title.textContent = 'Ask homeCore';
		const stopping = this.#run && !this.#confirm;
		go.innerHTML = stopping ? ICON.stop : ICON.send;
		go.setAttribute('aria-label', stopping ? 'Stop' : 'Send');

		const near = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
		const turns = this.#live ? [...this.#turns, this.#live] : this.#turns;
		body.innerHTML = turns.length ? turns.map((t, i) => this.#turnHtml(t, i === turns.length - 1)).join('') : this.#emptyHtml();
		if (toEnd || near) body.scrollTop = body.scrollHeight;
	}

	#emptyHtml() {
		const me = this.#me();
		const words = ROLE_WORDS[me.role] ?? `a ${String(me.role).replace(/_/g, ' ')} account`;
		const does = [me.can('devices:read') && 'answer questions', me.can('devices:command') && 'control devices',
			me.can('automations:write') && 'make automations'].filter(Boolean);
		const list = does.length > 1 ? `${does.slice(0, -1).join(', ')} and ${does.at(-1)}` : does[0] ?? 'answer questions';
		const who = me.isAdmin
			? ''
			: `<div class="who">Signed in as ${esc(words)}. The assistant can ${esc(list)}, the same as you can.</div>`;
		const ask = me.can('automations:write')
			? "What's on, what ran and why, or what you'd like to automate."
			: "What's on, what ran and why.";
		return `<div class="empty"><b>Ask about the house</b><span>${esc(ask)}</span></div>${who}`;
	}

	#turnHtml(turn, last) {
		if (turn.role === 'user') return `<div class="me">${esc(turn.text)}</div>`;
		const out = [];
		let chips = [];
		const flush = () => {
			if (chips.length) out.push(`<div class="chips">${chips.join('')}</div>`);
			chips = [];
		};
		for (const p of turn.parts ?? []) {
			if (p.kind === 'step') {
				chips.push(this.#chipHtml(p));
				continue;
			}
			flush();
			out.push(this.#partHtml(p, last));
		}
		flush();
		if (turn === this.#live) {
			if (this.#confirm) out.push(this.#confirmHtml(this.#confirm));
			else if (!(turn.parts ?? []).some((p) => p.kind === 'text')) out.push('<div class="typing" aria-label="Writing"><i></i><i></i><i></i></div>');
		}
		return `<div class="reply">${out.join('')}</div>`;
	}

	#chipHtml(p) {
		const icon = p.state === 'running' ? '<span class="spin"></span>' : p.state === 'failed' ? ICON.cross : ICON.check;
		return `<span class="chip ${p.state === 'failed' ? 'failed' : ''}">${icon}${esc(p.label)}</span>`;
	}

	#partHtml(p, last) {
		switch (p.kind) {
			case 'text':
				return prose(p.text);
			case 'devices':
				return `<section class="card" aria-label="${esc(p.title)}">
					${p.title ? `<h3>${esc(p.title)}</h3>` : ''}
					${(p.rows ?? []).map((r) => `<div class="row"><span class="what">${r.room ? `<b>${esc(r.room)}</b> · ` : ''}${esc(r.name)}</span>
						<span class="state ${r.lit ? 'lit' : ''}">${esc(r.state)}</span></div>`).join('')}
				</section>`;
			case 'suggestions':
				if (!last || this.#live) return '';
				return `<div class="suggest">${(p.options ?? []).map((o) => `<button type="button" class="btn" data-do="say" data-text="${esc(o)}">${esc(o)}</button>`).join('')}</div>`;
			case 'decided': {
				const words = {
					done: `Done: ${p.title}`,
					declined: `Not done: ${p.title}`,
					replied: `Not done yet: ${p.title}`,
					expired: `Not done, nobody answered: ${p.title}`,
					canceled: `Not done: ${p.title}`,
					failed: `Didn't work: ${p.title}${p.text ? `. ${p.text}` : ''}`
				}[p.outcome] ?? p.title;
				const icon = p.outcome === 'done' ? ICON.check : ICON.cross;
				const editor = p.rule_id
					? `<button type="button" class="link" data-do="editor" data-id="${esc(p.rule_id)}">Open in editor</button>`
					: '';
				return `<div class="decided ${esc(p.outcome)}">${icon}<span>${esc(words)}</span>${editor}</div>`;
			}
			case 'notice':
				return `<div class="notice ${p.bad ? 'bad' : ''}">${esc(p.text)}</div>`;
			default:
				return '';
		}
	}

	#confirmHtml(c) {
		const p = c.preview ?? {};
		const buttons = (c.choices ?? [])
			.map((b) => `<button type="button" class="btn ${b.danger ? 'danger' : b.primary ? 'primary' : ''}" data-do="choose" data-choice="${esc(b.id)}" ${c.sent ? 'disabled' : ''}>${esc(b.label)}</button>`)
			.join('');
		if (p.type === 'rule') {
			const lines = (xs) => (xs ?? []).map(esc).join('<br>');
			return `<section class="confirm rule" aria-label="Draft automation">
				<div class="top"><b>${esc(p.title)}</b>${p.badge ? `<span class="badge">${esc(p.badge)}</span>` : ''}</div>
				<dl>
					<dt>When</dt><dd>${lines(p.when) || '&nbsp;'}</dd>
					${(p.only_if ?? []).length ? `<dt>Only if</dt><dd>${lines(p.only_if)}</dd>` : ''}
					<dt>Do</dt><dd>${lines(p.do) || '&nbsp;'}</dd>
				</dl>
				${p.rule ? `<details><summary>The automation as homeCore keeps it</summary><pre>${esc(JSON.stringify(p.rule, null, 2))}</pre></details>` : ''}
				<div class="buttons">${buttons}</div>
			</section><p class="quiet">Or tell me what to change.</p>`;
		}
		return `<section class="confirm" aria-label="Check before doing">
			<b class="title">${esc(p.title)}</b>
			${p.detail ? `<span class="detail">${esc(p.detail)}</span>` : ''}
			<div class="buttons">${buttons}</div>
		</section>`;
	}

	#pastHtml() {
		const back = `<button type="button" class="pill" data-do="back-chat" style="align-self:flex-start">Back to the chat</button>`;
		if (this.#past === null) return `${back}<p class="quiet">Loading...</p>`;
		if (!Array.isArray(this.#past)) return `${back}<div class="notice bad">${esc(this.#past.error || 'Could not load your chats.')}</div>`;
		if (!this.#past.length) return `${back}<p class="quiet">No past chats.</p>`;
		return `${back}<div class="list">${this.#past
			.map((c) => `<div class="past"><button type="button" class="open" data-do="open" data-id="${esc(c.id)}">
				<span class="t">${esc(c.title || 'Chat')}</span><span class="d">${esc(when(c.updated))}</span></button>
				<button type="button" class="round bare" data-do="delete" data-id="${esc(c.id)}" aria-label="Delete ${esc(c.title || 'chat')}">${ICON.trash}</button></div>`)
			.join('')}</div>`;
	}
}

const SETTINGS_CSS = `
:host { display: block; color: var(--ink, #1e2126); font-family: var(--font, system-ui, sans-serif); }
* { box-sizing: border-box; }
button, input, select { font: inherit; }
.top { display: flex; flex-direction: column; gap: 4px; margin-bottom: 18px; }
.top h1 { margin: 0; font-size: 28px; font-weight: 800; }
.sub { color: var(--ink-muted, #5d6470); font-size: 14px; }
.ok { color: var(--good-ink, var(--ink, #1e2126)); font-weight: 700; }
.wait { color: var(--lit-ink, #8a4206); font-weight: 700; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; align-items: start; }
section { background: var(--surface, #fff); border: 1px solid var(--card-line, #e9e3d6); border-radius: var(--radius, 14px);
	padding: 20px; display: flex; flex-direction: column; gap: 14px; }
h2 { margin: 0; font-size: 17px; font-weight: 800; }
.field { display: flex; flex-direction: column; gap: 6px; font-weight: 700; font-size: 14px; }
.hint { font-weight: 500; color: var(--ink-muted, #5d6470); font-size: 13px; line-height: 1.4; }
.line { display: flex; gap: 8px; }
input[type=password], input[type=text], select { height: 42px; padding: 0 12px; border-radius: 11px; border: 1px solid var(--line, #e2dccf);
	background: var(--surface, #fff); color: var(--ink, #1e2126); font-size: 15px; font-weight: 500; min-width: 0; }
input[type=password] { flex: 1; }
input:disabled { color: var(--ink-muted, #5d6470); }
.btn { height: 42px; padding: 0 14px; border-radius: 21px; border: 1px solid var(--line, #e2dccf); background: var(--surface, #fff);
	color: var(--ink, #1e2126); font-weight: 700; cursor: pointer; white-space: nowrap; }
.btn.small { height: 36px; border-radius: 18px; align-self: flex-start; }
.btn.primary { border: none; background: var(--accent, #9a4a07); color: var(--accent-ink, #fff); }
.btn:disabled { opacity: 0.6; cursor: default; }
.may { gap: 4px; }
.may p { margin: 0 0 8px; color: var(--ink-muted, #5d6470); font-size: 14px; line-height: 1.45; }
.switch { display: flex; align-items: center; gap: 12px; min-height: 48px; border-top: 1px solid var(--card-line, #e9e3d6); cursor: pointer; }
.switch span { flex: 1; }
.switch b { font-size: 15px; }
.switch small { display: block; color: var(--ink-muted, #5d6470); font-size: 13px; }
.switch input { width: 20px; height: 20px; accent-color: var(--accent, #9a4a07); }
.keep { display: flex; align-items: center; gap: 12px; font-weight: 700; font-size: 14px; }
.keep span { flex: 1; }
.keep select { height: 38px; }
code { display: block; padding: 10px 12px; border-radius: 11px; background: var(--bg, #f3f0e8); font-family: var(--font-num, monospace); font-size: 13px; overflow-wrap: anywhere; }
a { color: var(--accent, #9a4a07); font-weight: 700; font-size: 14px; }
.said { font-size: 13px; color: var(--ink-muted, #5d6470); min-height: 1em; }
.said.bad { color: var(--alert, #b42318); }
.said.good { color: var(--good-ink, var(--ink, #1e2126)); }
`;

const SWITCHES = [
	['device_commands', 'Control devices', 'Lights, scenes, thermostats'],
	['rule_mutations', 'Make and change automations', ''],
	['security', 'Locks, doors and security', 'Devices marked Security in their settings'],
	['confirm', 'Ask before every change', "Shows what it's about to do and waits"]
];

/** Settings > Plugins > Assistant. */
class McpSettings extends HTMLElement {
	#host;
	#s = null;
	#error = '';
	#replacing = false;
	#accessTimer = undefined;
	#said = { key: '', test: '', save: '' };

	constructor() {
		super();
		this.attachShadow({ mode: 'open' });
	}

	set host(h) {
		if (this.#host === h) return;
		this.#host = h;
		const own = new CSSStyleSheet();
		own.replaceSync(SETTINGS_CSS);
		this.shadowRoot.adoptedStyleSheets = h?.theme?.sheet ? [h.theme.sheet, own] : [own];
		this.shadowRoot.addEventListener('click', (e) => this.#click(e));
		this.shadowRoot.addEventListener('change', (e) => this.#change(e));
		this.#load();
	}
	get host() {
		return this.#host;
	}

	async #load() {
		if (this.#host.me && !this.#host.me.isAdmin) {
			this.#error = "Only an admin can change the assistant's settings.";
			this.#draw();
			return;
		}
		const res = await this.#host.action('settings_get');
		if (!res.ok || res.data.ok === false) this.#error = (res.ok ? res.data.error : res.error) || 'The assistant did not answer.';
		else {
			this.#s = res.data;
			this.#error = '';
		}
		this.#draw();
		this.#awaitAccess();
	}

	/** Until homeCore has given the assistant its access, ask again now and then. */
	#awaitAccess() {
		clearTimeout(this.#accessTimer);
		if (!this.#s || this.#s.rest_access?.ready) return;
		this.#accessTimer = setTimeout(async () => {
			if (!this.isConnected) return;
			const res = await this.#host.action('settings_get');
			if (res.ok && res.data.ok !== false && res.data.rest_access?.ready) {
				this.#s = { ...this.#s, rest_access: res.data.rest_access };
				const line = this.shadowRoot.querySelector('.sub .wait');
				// Only the status line: someone may be halfway through typing a key.
				if (line) line.outerHTML = '<span class="ok">Connected to homeCore</span>';
				else this.#draw();
				return;
			}
			this.#awaitAccess();
		}, 3000);
	}

	disconnectedCallback() {
		clearTimeout(this.#accessTimer);
	}

	async #save(changes, what = 'save') {
		this.#said[what] = 'Saving...';
		this.#draw();
		const res = await this.#host.action('settings_set', changes);
		if (!res.ok || res.data.ok === false) {
			this.#said[what] = `Not saved: ${(res.ok ? res.data.error : res.error) || 'no answer'}`;
		} else {
			this.#s = res.data;
			this.#said[what] = 'Saved.';
		}
		this.#draw();
		return res.ok && res.data.ok !== false;
	}

	async #click(e) {
		const el = e.target.closest('[data-do]');
		if (!el) return;
		const root = this.shadowRoot;
		if (el.dataset.do === 'replace') {
			this.#replacing = true;
			this.#said.key = '';
			this.#draw();
			root.querySelector('#key')?.focus();
		} else if (el.dataset.do === 'keep') {
			this.#replacing = false;
			this.#draw();
		} else if (el.dataset.do === 'save-key') {
			const value = root.querySelector('#key').value.trim();
			if (!value) return;
			if (await this.#save({ api_key: value }, 'key')) this.#replacing = false;
			this.#draw();
		} else if (el.dataset.do === 'test') {
			const typed = this.#replacing ? root.querySelector('#key')?.value.trim() : '';
			this.#said.test = 'Testing...';
			this.#draw();
			const res = await this.#host.action('test_key', typed ? { api_key: typed } : {});
			const data = res.ok ? res.data : { ok: false, error: res.error };
			this.#said.test = data.ok ? data.message || 'The key works.' : data.error || 'The key did not work.';
			this.#said.testOk = !!data.ok;
			this.#draw();
		}
	}

	#change(e) {
		const el = e.target;
		if (el.dataset.switch) this.#save({ [el.dataset.switch]: el.checked });
		else if (el.id === 'model') this.#save({ model: el.value });
		else if (el.id === 'keep') this.#save({ retention: el.value });
	}

	#draw() {
		const root = this.shadowRoot;
		if (this.#error) {
			root.innerHTML = `<div class="top"><h1>Assistant</h1></div><section><p class="hint">${esc(this.#error)}</p></section>`;
			return;
		}
		const s = this.#s;
		if (!s) {
			root.innerHTML = `<div class="top"><h1>Assistant</h1><span class="sub">Loading...</span></div>`;
			return;
		}
		const typed = root.querySelector('#key')?.value ?? '';
		const access = s.rest_access?.ready
			? '<span class="ok">Connected to homeCore</span>'
			: '<span class="wait">Waiting for access to homeCore</span>';
		const keyHint = s.api_key_set && !this.#replacing
			? 'Saved. From console.anthropic.com. Questions and the house details needed to answer them go to Anthropic.'
			: 'From console.anthropic.com. Questions and the house details needed to answer them go to Anthropic.';
		const keyField = s.api_key_set && !this.#replacing
			? `<input type="password" value="placeholder-key" disabled aria-describedby="keyhint" aria-label="Claude API key, saved">
				<button type="button" class="btn" data-do="replace">Replace</button>`
			: `<input id="key" type="password" autocomplete="off" spellcheck="false" placeholder="sk-ant-..." aria-describedby="keyhint" value="${esc(typed)}">
				<button type="button" class="btn primary" data-do="save-key">Save</button>
				${s.api_key_set ? '<button type="button" class="btn" data-do="keep">Keep the old one</button>' : ''}`;
		const base = (() => {
			try {
				return window.location.origin;
			} catch {
				return 'http://homecore.local:8080';
			}
		})();
		root.innerHTML = `
			<div class="top">
				<h1>Assistant</h1>
				<span class="sub">hc-mcp ${esc(s.version ?? '')} · ${access}</span>
			</div>
			<div class="grid">
				<section aria-label="Model">
					<h2>Model</h2>
					<div class="field">
						<label for="key">Claude API key</label>
						<span class="line">${keyField}</span>
						<span id="keyhint" class="hint">${esc(keyHint)}</span>
						<span class="said" role="status">${esc(this.#said.key)}</span>
					</div>
					<label class="field">Model
						<select id="model">${(s.models ?? []).map((m) => `<option value="${esc(m.id)}" ${m.id === s.model ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}</select>
					</label>
					<button type="button" class="btn small" data-do="test">Test the key</button>
					<span class="said ${this.#said.test && this.#said.test !== 'Testing...' ? (this.#said.testOk ? 'good' : 'bad') : ''}" role="status">${esc(this.#said.test)}</span>
				</section>
				<section class="may" aria-label="What it may do">
					<h2 style="margin-bottom:4px">What it may do</h2>
					<p>It never goes beyond what the person asking may do. A household member can't change automations here either.</p>
					<label class="switch"><span><b>Answer questions</b><small>Devices, rooms, history, what ran and why</small></span>
						<input type="checkbox" checked disabled aria-label="Answer questions, always on"></label>
					${SWITCHES.map(([k, label, hint]) => `<label class="switch"><span><b>${esc(label)}</b>${hint ? `<small>${esc(hint)}</small>` : ''}</span>
						<input type="checkbox" data-switch="${k}" ${s[k] ? 'checked' : ''}></label>`).join('')}
					<span class="said" role="status">${esc(this.#said.save)}</span>
				</section>
				<section aria-label="Chats">
					<h2>Chats</h2>
					<label class="keep"><span>Keep each person's chats for</span>
						<select id="keep">${(s.retentions ?? []).map((r) => `<option value="${esc(r.id)}" ${r.id === s.retention ? 'selected' : ''}>${esc(r.label)}</option>`).join('')}</select>
					</label>
					<span class="hint">Kept by the assistant, not by homeCore. Each person sees only their own.</span>
				</section>
				<section aria-label="Other AI apps">
					<h2>Use from Claude Desktop or Claude Code</h2>
					<span class="hint" style="font-size:14px">The same tools work in any app that speaks MCP. Run hc-mcp on that computer and sign it in with your own API key.</span>
					<code>hc-mcp setup --base-url ${esc(base)}</code>
					<a href="https://github.com/homeCore-io/hc-mcp#readme" target="_blank" rel="noopener">How to set it up</a>
				</section>
			</div>`;
	}
}

if (!customElements.get('hc-mcp-chat')) customElements.define('hc-mcp-chat', McpChat);
if (!customElements.get('hc-mcp-settings')) customElements.define('hc-mcp-settings', McpSettings);
