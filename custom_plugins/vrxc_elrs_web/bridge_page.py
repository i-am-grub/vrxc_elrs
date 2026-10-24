"""
Browser bridge page.

Served by RotorHazard at /elrs_web. Open it in Chrome/Edge on the PC the
timer backpack (ESP) is plugged into: the page opens the ESP with Web Serial
and relays the MSP bytes to and from RotorHazard over socket.io.

The page extends RotorHazard's own layout, so it gets the same header,
menu, theme and server connection banner as the rest of the interface.
"""

from flask import Blueprint, render_template_string

PAGE = """{% extends "layout.html" %} {% block title %}{{ __('ELRS Backpack Bridge') }}{% endblock %} {% block head %}
<style>
.page-elrs-web .status-list {
	list-style: none;
	margin: 0;
	padding: 0;
}

.page-elrs-web .status-list li {
	display: flex;
	justify-content: space-between;
	gap: 1em;
	padding: 0.5em 0;
	border-bottom: 1px solid rgba(128, 128, 128, 0.35);
}

.page-elrs-web .status-dot {
	display: inline-block;
	width: 0.7em;
	height: 0.7em;
	margin-right: 0.5em;
	border-radius: 50%;
	background: #888;
}

.page-elrs-web .status-dot.ok { background: #3cb371; }
.page-elrs-web .status-dot.bad { background: #e0533d; }

.page-elrs-web #elrs-log {
	height: 12em;
	overflow: auto;
	margin: 0;
	font-family: monospace;
	font-size: 0.85em;
	white-space: pre-wrap;
	opacity: 0.8;
}

.page-elrs-web code {
	word-break: break-all;
}
</style>
<script type="text/javascript" charset="utf-8">
$(document).ready(function () {
	var BAUD = 460800;
	var port = null, writer = null, reader = null, readDone = null;
	var keepReading = false, writeChain = Promise.resolve(), wakeLock = null;
	var txBytes = 0, rxBytes = 0;
	var supported = window.isSecureContext && 'serial' in navigator;

	function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

	function log(msg) {
		var el = $('#elrs-log');
		el.append(document.createTextNode(new Date().toLocaleTimeString() + '  ' + msg + '\\n'));
		el.scrollTop(el[0].scrollHeight);
	}

	function toB64(bytes) {
		var s = '';
		for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
		return btoa(s);
	}

	function fromB64(b64) {
		var s = atob(b64), out = new Uint8Array(s.length);
		for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
		return out;
	}

	function setRH(ok) {
		$('#elrs-dot-rh').attr('class', 'status-dot ' + (ok ? 'ok' : 'bad'));
		$('#elrs-txt-rh').text(ok ? __('Connected') : __('Server connection lost'));
	}

	function setESP(open, text) {
		$('#elrs-dot-esp').attr('class', 'status-dot ' + (open ? 'ok' : ''));
		$('#elrs-txt-esp').text(text);
		$('#elrs-connect').prop('disabled', open || !supported);
		$('#elrs-disconnect').prop('disabled', !open);
	}

	if (!supported) {
		$('#elrs-unsupported').show();
		$('#elrs-origin').text(location.origin);
		$('#elrs-connect').prop('disabled', true);
	}

	// --- RotorHazard side ---------------------------------------------------

	setRH(socket.connected);
	socket.on('connect', function () {
		setRH(true);
		log('RotorHazard connected');
		// After a wifi drop, tell the server the ESP is still there
		if (port) socket.emit('elrs_web_state', { open: true });
	});
	socket.on('disconnect', function () {
		setRH(false);
		log('RotorHazard connection lost');
	});

	socket.on('elrs_web_tx', function (msg) {
		if (!writer) return;
		var bytes = fromB64(msg.d);
		writeChain = writeChain
			.then(function () { return writer && writer.write(bytes); })
			.then(function () { txBytes += bytes.length; $('#elrs-tx').text(txBytes); })
			.catch(function (e) { log('write error: ' + e.message); });
	});

	// --- ESP side (Web Serial) ----------------------------------------------

	async function readLoop() {
		while (port && port.readable && keepReading) {
			reader = port.readable.getReader();
			try {
				for (;;) {
					var r = await reader.read();
					if (r.done) break;
					if (r.value && r.value.length) {
						rxBytes += r.value.length; $('#elrs-rx').text(rxBytes);
						socket.emit('elrs_web_rx', { d: toB64(r.value) });
					}
				}
			} catch (e) {
				log('read error: ' + e.message);
			} finally {
				reader.releaseLock();
			}
		}
	}

	async function keepAwake() {
		try {
			if ('wakeLock' in navigator && !wakeLock) {
				wakeLock = await navigator.wakeLock.request('screen');
				wakeLock.addEventListener('release', function () { wakeLock = null; });
			}
		} catch (e) { /* not essential */ }
	}
	document.addEventListener('visibilitychange', function () {
		if (port && !document.hidden) keepAwake();
	});

	async function openPort(p) {
		await p.open({ baudRate: BAUD });
		// Dev kits reset on DTR/RTS toggles: keep both low, then give the ESP time to boot
		try { await p.setSignals({ dataTerminalReady: false, requestToSend: false }); } catch (e) {}
		port = p; writer = p.writable.getWriter();
		keepReading = true; readDone = readLoop();
		setESP(true, __('Opening') + '\\u2026');
		await sleep(2000);
		if (port !== p) return;
		setESP(true, __('Connected') + ' @ ' + BAUD + ' baud');
		log('ESP serial port open');
		keepAwake();
		socket.emit('elrs_web_state', { open: true });
	}

	async function closePort() {
		if (!port) return;
		var p = port;
		keepReading = false;
		port = null;
		socket.emit('elrs_web_state', { open: false });
		try { if (reader) await reader.cancel(); } catch (e) {}
		try { await readDone; } catch (e) {}
		try { if (writer) writer.releaseLock(); } catch (e) {}
		writer = null;
		try { await p.close(); } catch (e) {}
		if (wakeLock) wakeLock.release();
		setESP(false, __('Not connected'));
		log('ESP serial port closed');
	}

	$('#elrs-connect').on('click', async function () {
		try {
			await openPort(await navigator.serial.requestPort());
		} catch (e) {
			log('could not open the ESP: ' + e.message);
			await closePort();
		}
	});
	$('#elrs-disconnect').on('click', closePort);

	setESP(false, __('Not connected'));

	if (supported) {
		navigator.serial.addEventListener('disconnect', function (e) {
			if (e.target === port) { log('ESP unplugged'); closePort(); }
		});
		// Re-open the device already authorised on a previous visit, no click needed
		navigator.serial.getPorts().then(function (ports) {
			if (ports.length === 1) {
				openPort(ports[0]).catch(function (e) {
					log('auto-connect failed: ' + e.message);
					closePort();
				});
			}
		});
	}
});
</script>
{% endblock %} {% block content %}
<main class="page-elrs-web">

<div class="panel" id="elrs-unsupported" style="display:none">
	<div class="panel-header">
		<h2>{{ __('Web Serial is not available') }}</h2>
	</div>
	<div class="panel-content">
		<ol>
			<li>Use Chrome or Edge (Web Serial does not exist in Firefox or Safari).</li>
			<li>RotorHazard is served over plain http, which Chrome treats as insecure. Open
				<code>chrome://flags/#unsafely-treat-insecure-origin-as-secure</code>,
				add <code id="elrs-origin"></code> to the list, set the flag to <b>Enabled</b>
				and relaunch Chrome. This is needed once per PC.</li>
		</ol>
	</div>
</div>

<div class="panel">
	<div class="panel-header">
		<h2>{{ __('ELRS Backpack Bridge') }}</h2>
	</div>
	<div class="panel-content">
		<p>RotorHazard &harr; this PC &harr; USB &harr; ESP timer backpack &rarr; goggles</p>
		<ul class="status-list">
			<li><span><span class="status-dot" id="elrs-dot-rh"></span>RotorHazard</span>
				<span id="elrs-txt-rh"></span></li>
			<li><span><span class="status-dot" id="elrs-dot-esp"></span>ESP backpack (USB)</span>
				<span id="elrs-txt-esp"></span></li>
			<li><span>Sent to ESP / received from ESP</span>
				<span><span id="elrs-tx">0</span> B / <span id="elrs-rx">0</span> B</span></li>
		</ul>
		<div class="control-set">
			<button id="elrs-connect">Connect ESP</button>
			<button id="elrs-disconnect" disabled>Disconnect</button>
		</div>
	</div>
</div>

<div class="panel">
	<div class="panel-header">
		<h2>{{ __('Log') }}</h2>
	</div>
	<div class="panel-content">
		<pre id="elrs-log"></pre>
		<p>Keep this tab open during the event. In {{ __('Settings') }} &rarr;
			ELRS Backpack General Settings, set the connection type to <b>WEB</b>.</p>
	</div>
</div>

</main>
{% endblock %}
"""


def make_bridge_blueprint(rhapi) -> Blueprint:
    """
    Builds the blueprint serving the bridge page

    :param rhapi: The RotorHazard API, used to fill the layout's template variables
    """
    blueprint = Blueprint("elrs_web", __name__)

    @blueprint.route("/elrs_web")
    def bridge_page():
        # RotorHazard's own render helper adds these to every page; plugins
        # render through plain Flask, so provide what layout.html expects.
        try:
            server_info = rhapi._racecontext.serverstate.template_info_dict
            restart_flag = rhapi._racecontext.serverstate.restart_required
        except AttributeError:
            server_info = {"release_version": "", "about_html": ""}
            restart_flag = False

        return render_template_string(
            PAGE,
            serverInfo=server_info,
            getOption=rhapi.db.option,
            getConfig=rhapi.config.get,
            __=rhapi.__,
            Debug=rhapi.config.get("GENERAL", "DEBUG"),
            restart_flag=restart_flag,
        )

    return blueprint
